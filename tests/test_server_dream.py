"""Tests for the Dream run endpoints in server/main.py.

dream_memories/list_dream_runs/get_dream_run use the module-level
SessionLocal directly (matching main.py's own established convention,
e.g. _warn_if_unconfigured) rather than a Depends(get_db) parameter, so
they're exercised the same way test_server_export.py exercises router
functions that need a DB: call the function directly against a patched
SQLite SessionLocal, rather than going through TestClient (which would hit
the real Postgres URL main.py resolves at import time).
"""

import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

pytest.importorskip("fastapi", reason="fastapi not installed")

_SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)


@pytest.fixture
def test_session_factory():
    import models  # noqa: F401 -- registers all tables on Base.metadata before create_all
    from db import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def user(test_session_factory):
    from models import User

    session = test_session_factory()
    u = User(name="admin", email="admin@example.test", password_hash="x", role="admin")
    session.add(u)
    session.commit()
    session.refresh(u)
    session.close()
    return u


@pytest.fixture
def main_module(test_session_factory):
    """Import server/main.py once, patched so its DB calls hit the test
    SQLite engine and its Memory calls hit a mock instead of a real backend.

    Memory.from_config must be patched BEFORE import -- main.py calls
    initialize_state() at module level, which constructs a real Memory
    instance (and tries to open a real SQLite history file / Postgres
    connection) if not intercepted first, same as test_server_params.py's
    _mock_memory fixture.
    """
    mock_instance = MagicMock()
    with patch.dict(os.environ, {"AUTH_DISABLED": "true", "OPENAI_API_KEY": "fake-key"}):
        with patch("mem0.Memory.from_config", return_value=mock_instance):
            import main as main_module

            import importlib

            importlib.reload(main_module)

    with patch.object(main_module, "SessionLocal", test_session_factory):
        yield main_module


def _fg_background_tasks():
    """A stand-in for FastAPI's BackgroundTasks that runs tasks immediately
    instead of after the response -- lets tests assert on the outcome
    without needing an event loop / real ASGI response cycle."""
    class _Immediate:
        def add_task(self, func, *args, **kwargs):
            func(*args, **kwargs)

    return _Immediate()


def test_dream_run_created_and_dispatched(main_module, user):
    mock_memory = MagicMock()
    mock_memory.dream.return_value = {
        "processed": 4,
        "clusters_merged": 1,
        "new_memories_created": 1,
        "memories_merged": 2,
    }
    with patch.object(main_module, "get_memory_instance", return_value=mock_memory):
        result = main_module.dream_memories(
            main_module.DreamRequest(user_id="alice"),
            _fg_background_tasks(),
            user=user,
        )

    # The POST response is a snapshot taken before the background task runs
    # (matches real behavior: in production the task runs after the response
    # is already sent) -- always "running" at this point.
    assert result.status == "running"
    mock_memory.dream.assert_called_once_with(
        user_id="alice", agent_id=None, run_id=None, project=None, similarity_threshold=0.90, limit=100
    )

    # _fg_background_tasks() ran the task inline above, so by now the row is
    # updated -- fetch it fresh to see the outcome.
    fetched = main_module.get_dream_run(uuid.UUID(str(result.id)))
    assert fetched.status == "completed"
    assert fetched.processed == 4
    assert fetched.memories_merged == 2


def test_dream_run_missing_scope_400s_before_creating_a_row(main_module, user):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        main_module.dream_memories(main_module.DreamRequest(project="proj-a"), _fg_background_tasks(), user=user)

    assert exc_info.value.status_code == 400
    assert main_module.list_dream_runs(limit=50) == []


def test_dream_run_failure_recorded_as_failed(main_module, user):
    mock_memory = MagicMock()
    mock_memory.dream.side_effect = RuntimeError("vector store unavailable")
    with patch.object(main_module, "get_memory_instance", return_value=mock_memory):
        result = main_module.dream_memories(
            main_module.DreamRequest(user_id="alice"), _fg_background_tasks(), user=user
        )

    fetched = main_module.get_dream_run(uuid.UUID(str(result.id)))
    assert fetched.status == "failed"
    assert "vector store unavailable" in fetched.error


def test_concurrent_run_same_scope_returns_409(main_module, user):
    """The actual concurrency guard is a Postgres-only partial unique index
    (SQLite can't enforce it the same way), so exercise the code path
    directly: force db.commit() to raise the same IntegrityError a real
    unique-index violation would, and confirm dream_memories() translates
    that into a 409 rather than letting it bubble up as a 500, and never
    starts the background task for the rejected request."""
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    mock_memory = MagicMock()
    background_tasks = _fg_background_tasks()
    with patch.object(main_module, "get_memory_instance", return_value=mock_memory):
        with patch.object(Session, "commit", side_effect=IntegrityError("stmt", {}, Exception("dup"))):
            with pytest.raises(HTTPException) as exc_info:
                main_module.dream_memories(main_module.DreamRequest(user_id="alice"), background_tasks, user=user)

    assert exc_info.value.status_code == 409
    mock_memory.dream.assert_not_called()


def test_list_and_get_dream_runs(main_module, user):
    mock_memory = MagicMock()
    mock_memory.dream.return_value = {"processed": 1, "clusters_merged": 0, "new_memories_created": 0, "memories_merged": 0}
    with patch.object(main_module, "get_memory_instance", return_value=mock_memory):
        created = main_module.dream_memories(
            main_module.DreamRequest(user_id="bob"), _fg_background_tasks(), user=user
        )

    runs = main_module.list_dream_runs(limit=50)
    assert len(runs) == 1
    assert runs[0].user_id == "bob"

    fetched = main_module.get_dream_run(uuid.UUID(str(created.id)))
    assert fetched.id == created.id


def test_get_missing_dream_run_404s(main_module, user):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        main_module.get_dream_run(uuid.uuid4())

    assert exc_info.value.status_code == 404
