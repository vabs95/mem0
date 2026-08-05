"""Tests for /export (server/routers/export.py).

Calls the router functions directly against a plain in-memory SQLite
session, rather than going through TestClient -- same reasoning as
test_server_entities.py's db_session fixture: the request-logging
middleware in server/main.py opens its own raw SessionLocal() against the
real Postgres URL regardless of dependency_overrides, and module-level env
caching (JWT_SECRET/AUTH_DISABLED read once at import time) makes
TestClient-based tests order-dependent across files in this suite. Calling
the router functions directly exercises the exact same filtering/
serialization/CSV logic without any of that.
"""

import csv
import io
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

pytest.importorskip("fastapi", reason="fastapi not installed")

# server/ itself must be importable (main.py does `from auth import ...`,
# `from models import ...` etc, not `from server.auth import ...`), mirroring
# how it runs in Docker -- same trick as test_api_keys_router.py. Only the
# in-function imports below (db, models, routers.export) depend on this.
_SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)


@pytest.fixture
def db_session():
    import models  # noqa: F401 -- registers all tables on Base.metadata before create_all
    from db import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user(db_session):
    from models import User

    u = User(name="admin", email="admin@example.test", password_hash="x", role="admin")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _row(**payload):
    return SimpleNamespace(id="mem-" + payload.get("user_id", "x") + "-" + payload.get("project", ""), payload=payload)


MEMORY_ROWS = [
    [
        _row(data="alice note", user_id="alice", project="mem0", created_at="2026-08-01T00:00:00+00:00"),
        _row(data="bob note", user_id="bob", project="mem0", created_at="2026-08-02T00:00:00+00:00"),
        _row(data="alice homelab note", user_id="alice", project="homelab", created_at="2026-08-03T00:00:00+00:00"),
    ]
]


def _drain(streaming_response) -> bytes:
    """StreamingResponse.body_iterator is an async generator even when
    constructed from a plain sync iterable -- Starlette wraps it."""
    import asyncio

    async def _collect():
        chunks = []
        async for chunk in streaming_response.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        return b"".join(chunks)

    return asyncio.run(_collect())


@pytest.fixture
def mock_memory():
    mock_instance = MagicMock()
    mock_instance.vector_store.list.return_value = MEMORY_ROWS
    with patch("routers.export.get_memory_instance", return_value=mock_instance):
        yield mock_instance


def test_create_export_scoped_by_user(db_session, user, mock_memory):
    from routers.export import ExportCreateRequest, create_export

    result = create_export(ExportCreateRequest(format="json", user_id="alice"), user=user, db=db_session)

    assert result.record_count == 2
    assert result.status == "completed"
    assert result.filters == {"user_id": "alice"}
    assert {r["user_id"] for r in result.payload} == {"alice"}


def test_create_export_scoped_by_project(db_session, user, mock_memory):
    from routers.export import ExportCreateRequest, create_export

    result = create_export(ExportCreateRequest(format="csv", project="mem0"), user=user, db=db_session)

    assert result.record_count == 2
    assert {r["metadata"]["project"] for r in result.payload} == {"mem0"}


def test_create_export_date_range_filter(db_session, user, mock_memory):
    from datetime import datetime, timezone

    from routers.export import ExportCreateRequest, create_export

    result = create_export(
        ExportCreateRequest(format="json", date_from=datetime(2026, 8, 2, tzinfo=timezone.utc)),
        user=user,
        db=db_session,
    )

    assert result.record_count == 2  # bob's 08-02 note + alice's 08-03 note, not alice's 08-01 note


def test_list_exports_returns_created_export(db_session, user, mock_memory):
    from routers.export import ExportCreateRequest, create_export, list_exports

    create_export(ExportCreateRequest(format="json"), user=user, db=db_session)

    exports = list_exports(_user=user, db=db_session, limit=50)

    assert len(exports) == 1
    assert exports[0].record_count == 3


def test_download_json_export(db_session, user, mock_memory):
    import uuid

    from routers.export import ExportCreateRequest, create_export, download_export

    created = create_export(ExportCreateRequest(format="json", user_id="bob"), user=user, db=db_session)

    response = download_export(uuid.UUID(str(created.id)), _user=user, db=db_session)

    assert response.media_type == "application/json"
    parsed = json.loads(_drain(response))
    assert len(parsed["results"]) == 1
    assert parsed["results"][0]["user_id"] == "bob"


def test_download_csv_export(db_session, user, mock_memory):
    import uuid

    from routers.export import ExportCreateRequest, create_export, download_export

    created = create_export(ExportCreateRequest(format="csv", project="mem0"), user=user, db=db_session)

    response = download_export(uuid.UUID(str(created.id)), _user=user, db=db_session)

    assert response.media_type == "text/csv"
    rows = list(csv.DictReader(io.StringIO(_drain(response).decode())))
    assert len(rows) == 2


def test_delete_export_removes_it(db_session, user, mock_memory):
    import uuid

    from routers.export import ExportCreateRequest, create_export, delete_export, list_exports

    created = create_export(ExportCreateRequest(format="json"), user=user, db=db_session)

    delete_export(uuid.UUID(str(created.id)), _user=user, db=db_session)

    assert list_exports(_user=user, db=db_session, limit=50) == []


def test_download_missing_export_404s(db_session, user):
    import uuid

    from fastapi import HTTPException
    from routers.export import download_export

    with pytest.raises(HTTPException) as exc_info:
        download_export(uuid.uuid4(), _user=user, db=db_session)

    assert exc_info.value.status_code == 404
