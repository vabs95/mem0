from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_DIR = os.path.join(ROOT, "server", "mcp")
if MCP_DIR not in sys.path:
    sys.path.insert(0, MCP_DIR)

from mem0_mcp_bridge.client import build_filters  # noqa: E402


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
