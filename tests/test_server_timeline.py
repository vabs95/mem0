"""Tests for the /timeline/events REST endpoints (server/routers/timeline.py).

Uses an in-memory SQLite session (via FastAPI dependency override) instead of
a real Postgres instance — this router's SQL is simple CRUD/filtering with no
Postgres-specific features, so SQLite is a faithful enough stand-in for tests.
"""

import importlib
import os
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
    with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key"}):
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

    # StaticPool: plain sqlite:///:memory: hands each pooled connection its
    # own blank in-memory database — StaticPool pins the whole test to one
    # shared connection so create_all()'s tables are actually visible later.
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


def test_create_and_list_event(client):
    resp = client.post(
        "/timeline/events",
        json={
            "event_type": "session_start",
            "source_agent": "claude-code",
            "user_id": "u1",
            "project": "mem0",
            "summary": "started session",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["event_type"] == "session_start"
    assert body["project"] == "mem0"

    resp = client.get("/timeline/events", params={"user_id": "u1"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["source_agent"] == "claude-code"


def test_list_events_filters_by_project(client):
    client.post("/timeline/events", json={"event_type": "stop", "source_agent": "codex", "project": "proj-a"})
    client.post("/timeline/events", json={"event_type": "stop", "source_agent": "codex", "project": "proj-b"})

    resp = client.get("/timeline/events", params={"project": "proj-a"})
    items = resp.json()
    assert len(items) == 1
    assert items[0]["project"] == "proj-a"


def test_list_events_respects_limit(client):
    for i in range(5):
        client.post("/timeline/events", json={"event_type": "tool_use", "source_agent": "hermes", "run_id": f"r{i}"})

    resp = client.get("/timeline/events", params={"limit": 2})
    assert len(resp.json()) == 2
