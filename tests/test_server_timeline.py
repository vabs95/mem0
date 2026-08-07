"""Tests for the /timeline/events REST endpoints (server/routers/timeline.py).

Uses an in-memory SQLite session (via FastAPI dependency override) instead of
a real Postgres instance — this router's SQL is simple CRUD/filtering with no
Postgres-specific features, so SQLite is a faithful enough stand-in for tests.
"""

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

# server/ itself must be importable (main.py does `from auth import ...`,
# `from models import ...` etc, not `from server.auth import ...`), mirroring
# how it runs in Docker -- same trick as test_api_keys_router.py. Makes this
# file runnable standalone instead of depending on another test file having
# already done this during the same pytest session.
_SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)


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


@pytest.fixture
def client_auth_enabled(_mock_memory):
    """Same as `client`, but with AUTH_DISABLED unset -- for asserting that
    /timeline/events actually enforces verify_auth rather than only ever
    being exercised through the AUTH_DISABLED=true fixture."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "", "AUTH_DISABLED": "", "JWT_SECRET": "test-secret"}):
        import auth as server_auth
        import db as server_db
        import server.main as server_main

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


def test_create_event_with_category_and_memory_ids(client):
    resp = client.post(
        "/timeline/events",
        json={
            "event_type": "add_memory",
            "source_agent": "codex",
            "user_id": "u1",
            "category": "decision",
            "memory_ids": ["mem-1", "mem-2"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "decision"
    assert body["memory_ids"] == ["mem-1", "mem-2"]

    resp = client.get("/timeline/events", params={"user_id": "u1"})
    items = resp.json()
    assert len(items) == 1
    assert items[0]["memory_ids"] == ["mem-1", "mem-2"]


def test_create_event_defaults_memory_ids_to_empty_list(client):
    resp = client.post("/timeline/events", json={"event_type": "stop", "source_agent": "codex"})
    assert resp.status_code == 200
    assert resp.json()["memory_ids"] == []
    assert resp.json()["category"] is None


def test_list_events_filters_by_category(client):
    client.post(
        "/timeline/events",
        json={"event_type": "add_memory", "source_agent": "codex", "category": "decision"},
    )
    client.post(
        "/timeline/events",
        json={"event_type": "add_memory", "source_agent": "codex", "category": "bug_fix"},
    )

    resp = client.get("/timeline/events", params={"category": "decision"})
    items = resp.json()
    assert len(items) == 1
    assert items[0]["category"] == "decision"


def test_get_events_for_memory_backlink(client):
    client.post(
        "/timeline/events",
        json={"event_type": "add_memory", "source_agent": "codex", "memory_ids": ["mem-a"]},
    )
    client.post(
        "/timeline/events",
        json={"event_type": "add_memory", "source_agent": "codex", "memory_ids": ["mem-b"]},
    )

    resp = client.get("/timeline/events/for-memory/mem-a")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["memory_ids"] == ["mem-a"]

    resp = client.get("/timeline/events/for-memory/mem-nonexistent")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_events_with_no_filters_returns_everything(client):
    client.post("/timeline/events", json={"event_type": "stop", "source_agent": "codex", "project": "proj-a"})
    client.post("/timeline/events", json={"event_type": "stop", "source_agent": "claude-code", "user_id": "u1"})

    resp = client.get("/timeline/events")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_events_require_auth_when_auth_is_enabled(client_auth_enabled):
    resp = client_auth_enabled.post(
        "/timeline/events", json={"event_type": "stop", "source_agent": "codex"}
    )
    assert resp.status_code == 401

    resp = client_auth_enabled.get("/timeline/events")
    assert resp.status_code == 401
