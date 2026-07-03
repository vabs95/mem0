from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_DIR = os.path.join(ROOT, "server", "mcp")
if MCP_DIR not in sys.path:
    sys.path.insert(0, MCP_DIR)

from mem0_mcp_bridge.client import app_id_to_agent_id, default_user_filter


def test_bridge_maps_app_id_to_agent_id():
    payload = app_id_to_agent_id({"user_id": "demo-user", "app_id": "mem0", "messages": []})

    assert payload["agent_id"] == "mem0"
    assert "app_id" not in payload


def test_bridge_default_filter_maps_app_id():
    filters = default_user_filter("demo-user", {"AND": [{"app_id": "mem0"}]})

    assert {"agent_id": "mem0"} in filters["AND"]
    assert {"app_id": "mem0"} not in filters["AND"]


def test_bridge_default_filter_injects_user_id():
    filters = default_user_filter("demo-user", {"metadata": {"type": "decision"}})

    assert filters["AND"][0] == {"user_id": "demo-user"}
    assert {"metadata": {"type": "decision"}} in filters["AND"]
