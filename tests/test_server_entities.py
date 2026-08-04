"""Tests for GET/DELETE /entities (server/routers/entities.py).

Covers the "project" entity type added alongside user/agent/run — project
isn't a real mem0 entity (no dedicated column), it's a metadata tag, so
these tests exist specifically to pin down that list_entities buckets by it
and DELETE /entities/project/{id} correctly maps to delete_all(project=...).
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")

from fastapi.testclient import TestClient


@pytest.fixture
def _mock_memory():
    mock_instance = MagicMock()
    mock_instance.delete_all.return_value = {"message": "Memories deleted"}
    with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key", "ADMIN_API_KEY": ""}):
        with patch("mem0.Memory.from_config", return_value=mock_instance):
            yield mock_instance


@pytest.fixture
def client(_mock_memory):
    import server.main as server_main

    return TestClient(server_main.app)


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


class TestDeleteProjectEntity:
    def test_delete_project_entity_calls_delete_all_with_project(self, client, _mock_memory):
        resp = client.delete("/entities/project/my-project")

        assert resp.status_code == 200
        _mock_memory.delete_all.assert_called_once_with(project="my-project")

    def test_delete_entity_still_supports_existing_types(self, client, _mock_memory):
        resp = client.delete("/entities/user/alice")

        assert resp.status_code == 200
        _mock_memory.delete_all.assert_called_once_with(user_id="alice")

    def test_delete_entity_rejects_unknown_type(self, client, _mock_memory):
        resp = client.delete("/entities/bogus/whatever")

        assert resp.status_code == 422
        _mock_memory.delete_all.assert_not_called()
