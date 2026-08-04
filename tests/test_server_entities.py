"""Tests for GET/DELETE /entities (server/routers/entities.py).

Covers the "project" entity type added alongside user/agent/run — project
isn't a real mem0 entity (no dedicated column), it's a metadata tag, so
these tests exist specifically to pin down that list_entities buckets by it
and DELETE /entities/project/{id} correctly maps to delete_all(project=...).

Also covers that deleting an entity clears its TimelineEvent history too
(same scoping fields), not just its memories — otherwise deleted entities
leave orphaned, unreachable timeline rows behind. Uses an in-memory SQLite
session (via FastAPI dependency override), same approach as
test_server_timeline.py, since this router's delete is simple CRUD with no
Postgres-specific features.
"""

import importlib
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def _mock_memory():
    mock_instance = MagicMock()
    mock_instance.delete_all.return_value = {"message": "Memories deleted"}
    with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key", "ADMIN_API_KEY": ""}):
        with patch("mem0.Memory.from_config", return_value=mock_instance):
            yield mock_instance


@pytest.fixture
def client(_mock_memory):
    with patch.dict(os.environ, {"ADMIN_API_KEY": "", "AUTH_DISABLED": "true"}):
        import auth as server_auth
        import db as server_db
        import server.main as server_main

        # Note: only auth/main are reloaded, not db — routers/*.py already
        # hold a reference to db.get_db from their own first import, and
        # reloading db.py here would create a second, distinct function
        # object that the routers never see, silently defeating the
        # dependency_overrides applied below.
        importlib.reload(server_auth)
        importlib.reload(server_main)

    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    server_db.Base.metadata.create_all(bind=test_engine)

    def _override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    server_main.app.dependency_overrides[server_db.get_db] = _override_get_db
    yield TestClient(server_main.app)
    server_main.app.dependency_overrides.clear()


def _row(**payload):
    return SimpleNamespace(payload=payload)


class TestListEntitiesBucketsByProject:
    def test_project_appears_alongside_user_agent_run(self, client, _mock_memory):
        _mock_memory.vector_store.list.return_value = [
            [
                _row(
                    user_id="alice",
                    agent_id="forge",
                    project="mem0",
                    created_at="2026-08-01T00:00:00+00:00",
                    updated_at="2026-08-01T00:00:00+00:00",
                ),
                _row(
                    user_id="alice",
                    agent_id="hermes",
                    project="mem0",
                    created_at="2026-08-02T00:00:00+00:00",
                    updated_at="2026-08-02T00:00:00+00:00",
                ),
                _row(
                    user_id="alice",
                    agent_id="forge",
                    project="homelab",
                    created_at="2026-08-03T00:00:00+00:00",
                    updated_at="2026-08-03T00:00:00+00:00",
                ),
            ]
        ]

        resp = client.get("/entities")

        assert resp.status_code == 200
        entities = {(e["type"], e["id"]): e for e in resp.json()}

        # Cross-agent-same-project: both forge and hermes contributed to
        # "mem0", so the project bucket must count all three memories,
        # not just the ones from one agent.
        assert entities[("project", "mem0")]["total_memories"] == 2
        assert entities[("project", "homelab")]["total_memories"] == 1
        assert entities[("user", "alice")]["total_memories"] == 3
        assert entities[("agent", "forge")]["total_memories"] == 2
        assert entities[("agent", "hermes")]["total_memories"] == 1

    def test_memories_without_project_dont_create_a_bucket(self, client, _mock_memory):
        _mock_memory.vector_store.list.return_value = [
            [_row(user_id="alice")],
        ]

        resp = client.get("/entities")

        assert resp.status_code == 200
        types = {e["type"] for e in resp.json()}
        assert "project" not in types


@pytest.fixture
def db_session():
    """Plain in-memory SQLite session, no app/TestClient/middleware involved.

    DELETE /entities routes through server.main's request-logging middleware
    (_persist_request_log in server/main.py), which opens its own raw
    SessionLocal() against the real Postgres URL regardless of the
    dependency_overrides used elsewhere — unrelated to entities.py, but it
    makes TestClient-based DELETE requests fail without a live Postgres
    instance. These tests call the router function directly instead, which
    exercises the exact same delete_entity()/TimelineEvent logic without
    going through the HTTP/middleware stack.
    """
    from db import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


class TestDeleteProjectEntity:
    def test_delete_project_entity_calls_delete_all_with_project(self, db_session):
        from routers.entities import delete_entity

        # get_memory_instance() is a process-wide singleton (server_state.py)
        # left over from whichever test's TestClient/app reload initialized
        # it first — patch it directly here rather than relying on that
        # shared state or the mem0.Memory.from_config patch that seeds it.
        mock_instance = MagicMock()
        with patch("routers.entities.get_memory_instance", return_value=mock_instance):
            result = delete_entity("project", "my-project", db=db_session)

        assert result.message == "Entity deleted"
        mock_instance.delete_all.assert_called_once_with(project="my-project")

    def test_delete_entity_still_supports_existing_types(self, db_session):
        from routers.entities import delete_entity

        mock_instance = MagicMock()
        with patch("routers.entities.get_memory_instance", return_value=mock_instance):
            result = delete_entity("user", "alice", db=db_session)

        assert result.message == "Entity deleted"
        mock_instance.delete_all.assert_called_once_with(user_id="alice")


class TestDeleteEntityClearsTimeline:
    def test_delete_project_entity_clears_its_timeline_events(self, _mock_memory, db_session):
        from routers.entities import delete_entity
        from routers.timeline import TimelineEventCreate, create_event, list_events

        create_event(
            TimelineEventCreate(event_type="session_start", source_agent="claude-code", project="my-project"),
            db=db_session,
        )
        create_event(
            TimelineEventCreate(event_type="session_start", source_agent="claude-code", project="other-project"),
            db=db_session,
        )

        delete_entity("project", "my-project", db=db_session)

        remaining_projects = {e.project for e in list_events(db=db_session, limit=50)}
        assert "my-project" not in remaining_projects
        assert "other-project" in remaining_projects

    def test_delete_user_entity_clears_its_timeline_events(self, _mock_memory, db_session):
        from routers.entities import delete_entity
        from routers.timeline import TimelineEventCreate, create_event, list_events

        create_event(
            TimelineEventCreate(event_type="session_start", source_agent="codex", user_id="alice"), db=db_session
        )
        create_event(
            TimelineEventCreate(event_type="session_start", source_agent="codex", user_id="bob"), db=db_session
        )

        delete_entity("user", "alice", db=db_session)

        remaining_users = {e.user_id for e in list_events(db=db_session, limit=50)}
        assert "alice" not in remaining_users
        assert "bob" in remaining_users
