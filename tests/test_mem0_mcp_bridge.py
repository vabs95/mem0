from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_DIR = os.path.join(ROOT, "server", "mcp")
if MCP_DIR not in sys.path:
    sys.path.insert(0, MCP_DIR)

from mem0_mcp_bridge.client import build_filters  # noqa: E402
from mem0_mcp_bridge.server import _effective_project  # noqa: E402


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
    extra = {"metadata": {"type": "decision"}}
    filters = build_filters(
        user_id="demo-user",
        project="demo-project",
        extra=extra,
    )

    assert filters["user_id"] == "demo-user"
    assert filters["project"] == "demo-project"
    assert filters["metadata"] == {"type": "decision"}
