from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def test_self_hosted_add_memory_maps_app_id_to_agent_id(monkeypatch):
    from _api import add_memory

    monkeypatch.setenv("MEM0_API_MODE", "self_hosted")
    monkeypatch.setenv("MEM0_API_URL", "https://mem0.example.test")

    captured = {}

    def mock_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'{"results":[]}'
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        add_memory("m0sk-test", {"messages": [], "user_id": "demo-user", "app_id": "mem0"})

    assert captured["url"] == "https://mem0.example.test/memories"
    assert captured["headers"]["X-api-key"] == "m0sk-test"
    assert captured["body"]["agent_id"] == "mem0"
    assert "app_id" not in captured["body"]


def test_self_hosted_search_maps_app_id_filter(monkeypatch):
    from _api import search_memories

    monkeypatch.setenv("MEM0_API_MODE", "self_hosted")
    monkeypatch.setenv("MEM0_API_URL", "https://mem0.example.test")

    captured = {}

    def mock_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'{"results":[]}'
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        search_memories(
            "m0sk-test",
            {"query": "decisions", "filters": {"AND": [{"user_id": "demo-user"}, {"app_id": "mem0"}]}},
        )

    assert captured["body"]["filters"]["agent_id"] == "mem0"
    assert captured["body"]["filters"]["user_id"] == "demo-user"
    assert "app_id" not in captured["body"]["filters"]
    assert "AND" not in captured["body"]["filters"]
