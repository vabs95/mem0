from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_DIR = os.path.join(ROOT, "server", "mcp")
if MCP_DIR not in sys.path:
    sys.path.insert(0, MCP_DIR)

pytest.importorskip("mcp", reason="mcp not installed (see server/mcp/requirements.txt)")

from mem0_mcp_bridge.client import build_filters  # noqa: E402
from mem0_mcp_bridge.server import _dream_consolidate_and_wait, _effective_project, add_memory  # noqa: E402


def test_effective_project_prefers_explicit_project():
    assert _effective_project("proj-a", "app-b") == "proj-a"


def test_effective_project_falls_back_to_app_id_alias():
    # app_id is mem0's hosted-API field name for the same concept (see
    # mem0/client/main.py ENTITY_PARAMS) — the self-hosted MCP bridge must
    # accept it too so hosted-API-style agent instructions still work here.
    assert _effective_project(None, "app-b") == "app-b"


def test_effective_project_none_when_neither_given():
    assert _effective_project(None, None) is None


def test_build_filters_basic():
    filters = build_filters(
        user_id="demo-user",
        agent_id="demo-agent",
        run_id="demo-run",
        project="demo-project",
    )

    assert filters["user_id"] == "demo-user"
    assert filters["agent_id"] == "demo-agent"
    assert filters["run_id"] == "demo-run"
    assert filters["project"] == "demo-project"


def test_build_filters_with_extra():
    """A nested "metadata" dict in extra must lift to top-level keys --
    self-hosted stores metadata fields flat on the payload, so a nested
    "metadata" key matches nothing and silently zeroes out the query."""
    extra = {"metadata": {"type": "decision"}}
    filters = build_filters(
        user_id="demo-user",
        project="demo-project",
        extra=extra,
    )

    assert filters == {"user_id": "demo-user", "project": "demo-project", "type": "decision"}
    assert "metadata" not in filters


def test_build_filters_translates_app_id_inside_extra():
    """Agents commonly repeat app_id inside their own filters argument in
    addition to the top-level app_id param. Self-hosted memories store this
    concept as "project", not "app_id" -- an unrecognized "app_id" key
    reaching the backend doesn't error, it just matches nothing and zeroes
    out the whole query."""
    filters = build_filters(
        user_id="demo-user",
        project="demo-project",
        extra={"user_id": "demo-user", "app_id": "demo-project", "type": "decision"},
    )

    assert filters == {"user_id": "demo-user", "project": "demo-project", "type": "decision"}
    assert "app_id" not in filters


def test_build_filters_flattens_and_clause_with_nested_metadata():
    """Real failure mode from a live Codex session: the agent sent
    {"AND": [{"user_id": ...}, {"app_id": ...}, {"metadata": {"type": ...}}]}
    -- the exact cloud-style shape the hosted platform API accepts. Against
    self-hosted this must collapse to a flat dict or the backend rejects it
    with a 400 ("AND" isn't a recognized filter key)."""
    filters = build_filters(
        user_id="demo-user",
        project="demo-project",
        extra={
            "AND": [
                {"user_id": "demo-user"},
                {"app_id": "demo-project"},
                {"metadata": {"type": "decision"}},
            ]
        },
    )

    assert filters == {"user_id": "demo-user", "project": "demo-project", "type": "decision"}
    assert "AND" not in filters
    assert "app_id" not in filters
    assert "metadata" not in filters


def test_add_memory_merges_importance_and_category_into_metadata(monkeypatch):
    """importance/category are dedicated MCP tool params for discoverability,
    but the backend only understands them as payload/metadata fields -- they
    must be merged into the outgoing metadata dict, not sent as separate
    top-level request fields the backend would silently ignore."""
    captured = {}

    def fake_request(method, path, *, json_body=None, params=None):
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        return {"ok": True}

    from mem0_mcp_bridge import server as server_module

    monkeypatch.setattr(server_module, "_client", lambda: type("C", (), {"request": staticmethod(fake_request)})())

    add_memory(text="likes dark mode", user_id="demo-user", importance=8, category="preference")

    assert captured["path"] == "/memories"
    assert captured["json_body"]["metadata"]["importance"] == 8
    assert captured["json_body"]["metadata"]["category"] == "preference"


def test_dream_consolidate_polls_until_run_completes(monkeypatch):
    """POST /memories/dream now returns immediately with status="running"
    (it's a background job server-side) -- the MCP tool must poll the run
    status endpoint until it settles, not just relay the initial "running"
    response back to the agent."""
    from mem0_mcp_bridge import server as server_module

    monkeypatch.setattr(server_module, "DREAM_POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(server_module, "time", type("T", (), {"monotonic": staticmethod(lambda: 0.0), "sleep": staticmethod(lambda _: None)}))

    calls = []
    poll_responses = iter(
        [
            {"id": "run-1", "status": "running"},
            {"id": "run-1", "status": "running"},
            {"id": "run-1", "status": "completed", "memories_merged": 4},
        ]
    )

    def fake_request(method, path, *, json_body=None, params=None):
        calls.append((method, path))
        if method == "POST":
            return {"id": "run-1", "status": "running"}
        return next(poll_responses)

    monkeypatch.setattr(server_module, "_client", lambda: type("C", (), {"request": staticmethod(fake_request)})())
    result = _dream_consolidate_and_wait({"user_id": "demo-user"})

    assert result == {"id": "run-1", "status": "completed", "memories_merged": 4}
    assert calls[0] == ("POST", "/memories/dream")
    assert calls.count(("GET", "/memories/dream/runs/run-1")) == 3


def test_dream_consolidate_returns_immediately_if_already_settled(monkeypatch):
    """A run that completes synchronously fast enough to already be
    non-"running" on the initial POST response shouldn't trigger any polling."""
    from mem0_mcp_bridge import server as server_module

    calls = []

    def fake_request(method, path, *, json_body=None, params=None):
        calls.append((method, path))
        return {"id": "run-1", "status": "completed", "memories_merged": 0}

    monkeypatch.setattr(server_module, "_client", lambda: type("C", (), {"request": staticmethod(fake_request)})())

    result = _dream_consolidate_and_wait({"user_id": "demo-user"})

    assert result["status"] == "completed"
    assert calls == [("POST", "/memories/dream")]
