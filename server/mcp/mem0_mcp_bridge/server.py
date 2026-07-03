from __future__ import annotations

import json
import logging
import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from .client import Mem0SelfHostedClient, app_id_to_agent_id, app_filters_to_agent_filters, default_user_filter

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("mem0_mcp_bridge")

DEFAULT_USER_ID = os.environ.get("MEM0_DEFAULT_USER_ID", "mem0-mcp")
DEFAULT_AGENT_ID = os.environ.get("MEM0_DEFAULT_AGENT_ID") or os.environ.get("MEM0_DEFAULT_APP_ID", "")


def _json_call(func, *args, **kwargs) -> str:
    try:
        return json.dumps(func(*args, **kwargs), ensure_ascii=False)
    except Exception as exc:
        logger.exception("Mem0 MCP bridge call failed")
        return json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False)


def _client() -> Mem0SelfHostedClient:
    return Mem0SelfHostedClient.from_env()


server = FastMCP(
    "mem0",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8765")),
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@server.tool(description="Store a new preference, fact, or conversation snippet.")
def add_memory(
    text: Annotated[str | None, Field(default=None, description="Plain sentence summarizing what to store.")] = None,
    messages: Annotated[list[dict[str, str]] | None, Field(default=None, description="Role/content messages.")] = None,
    user_id: Annotated[str | None, Field(default=None, description="User scope.")] = None,
    agent_id: Annotated[str | None, Field(default=None, description="Agent scope.")] = None,
    app_id: Annotated[str | None, Field(default=None, description="Alias for agent_id in self-hosted mode.")] = None,
    run_id: Annotated[str | None, Field(default=None, description="Run/session scope.")] = None,
    metadata: Annotated[dict[str, Any] | None, Field(default=None, description="Metadata JSON.")] = None,
    infer: Annotated[bool, Field(default=True, description="Whether Mem0 should extract facts.")] = True,
) -> str:
    if not messages:
        if not text:
            return json.dumps({"error": "messages_missing", "detail": "Provide text or messages."})
        messages = [{"role": "user", "content": text}]

    payload = app_id_to_agent_id(
        {
            "messages": messages,
            "user_id": user_id or DEFAULT_USER_ID,
            "agent_id": agent_id or DEFAULT_AGENT_ID or None,
            "app_id": app_id,
            "run_id": run_id,
            "metadata": metadata,
            "infer": infer,
        }
    )
    payload = {k: v for k, v in payload.items() if v is not None}
    return _json_call(_client().request, "POST", "/memories", json_body=payload)


@server.tool(description="Run a semantic search over existing memories.")
def search_memories(
    query: Annotated[str, Field(description="Natural language search query.")],
    filters: Annotated[dict[str, Any] | None, Field(default=None, description="Structured filters.")] = None,
    limit: Annotated[int | None, Field(default=None, description="Maximum results.")] = None,
    top_k: Annotated[int | None, Field(default=None, description="Maximum results alias.")] = None,
    threshold: Annotated[float | None, Field(default=None, description="Minimum similarity score.")] = None,
) -> str:
    payload: dict[str, Any] = {
        "query": query,
        "filters": default_user_filter(DEFAULT_USER_ID, filters),
        "top_k": top_k or limit,
        "threshold": threshold,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    return _json_call(_client().request, "POST", "/search", json_body=payload)


@server.tool(description="List memories using structured filters.")
def get_memories(
    filters: Annotated[dict[str, Any] | None, Field(default=None, description="Structured filters.")] = None,
    page_size: Annotated[int | None, Field(default=None, description="Maximum memories to list.")] = None,
    top_k: Annotated[int | None, Field(default=None, description="Maximum memories alias.")] = None,
) -> str:
    scoped = default_user_filter(DEFAULT_USER_ID, filters)
    params: dict[str, Any] = {"top_k": top_k or page_size}
    for clause in scoped.get("AND", []):
        if isinstance(clause, dict):
            for key in ("user_id", "agent_id", "run_id"):
                if key in clause and isinstance(clause[key], str) and clause[key] != "*":
                    params[key] = clause[key]
    return _json_call(_client().request, "GET", "/memories", params=params)


@server.tool(description="Fetch a single memory by ID.")
def get_memory(memory_id: Annotated[str, Field(description="Memory ID.")]) -> str:
    return _json_call(_client().request, "GET", f"/memories/{memory_id}")


@server.tool(description="Overwrite an existing memory's text.")
def update_memory(
    memory_id: Annotated[str, Field(description="Memory ID.")],
    text: Annotated[str, Field(description="Replacement memory text.")],
    metadata: Annotated[dict[str, Any] | None, Field(default=None, description="Optional replacement metadata.")] = None,
) -> str:
    payload = {"text": text}
    if metadata is not None:
        payload["metadata"] = metadata
    return _json_call(_client().request, "PUT", f"/memories/{memory_id}", json_body=payload)


@server.tool(description="Delete one memory by ID.")
def delete_memory(memory_id: Annotated[str, Field(description="Memory ID.")]) -> str:
    return _json_call(_client().request, "DELETE", f"/memories/{memory_id}")


@server.tool(description="Delete every memory in a user/agent/run scope.")
def delete_all_memories(
    user_id: Annotated[str | None, Field(default=None, description="User scope.")] = None,
    agent_id: Annotated[str | None, Field(default=None, description="Agent scope.")] = None,
    app_id: Annotated[str | None, Field(default=None, description="Alias for agent_id.")] = None,
    run_id: Annotated[str | None, Field(default=None, description="Run scope.")] = None,
) -> str:
    params = app_id_to_agent_id(
        {
            "user_id": user_id or DEFAULT_USER_ID,
            "agent_id": agent_id,
            "app_id": app_id,
            "run_id": run_id,
        }
    )
    return _json_call(_client().request, "DELETE", "/memories", params=params)


@server.tool(description="List users, agents, and runs currently holding memories.")
def list_entities() -> str:
    return _json_call(_client().request, "GET", "/entities")


@server.tool(description="Delete a user/agent/run entity and its memories.")
def delete_entities(
    user_id: Annotated[str | None, Field(default=None, description="User entity to delete.")] = None,
    agent_id: Annotated[str | None, Field(default=None, description="Agent entity to delete.")] = None,
    app_id: Annotated[str | None, Field(default=None, description="Alias for agent entity.")] = None,
    run_id: Annotated[str | None, Field(default=None, description="Run entity to delete.")] = None,
) -> str:
    mapped = app_id_to_agent_id({"user_id": user_id, "agent_id": agent_id, "app_id": app_id, "run_id": run_id})
    scopes = [(key[:-3], value) for key, value in mapped.items() if value and key.endswith("_id")]
    if len(scopes) != 1:
        return json.dumps({"error": "scope_invalid", "detail": "Provide exactly one user_id, agent_id/app_id, or run_id."})
    entity_type, entity_id = scopes[0]
    return _json_call(_client().request, "DELETE", f"/entities/{entity_type}/{entity_id}")


@server.prompt()
def memory_assistant() -> str:
    return (
        "Use Mem0 tools for long-term memory. Prefer scoped filters with user_id and app_id/agent_id. "
        "Store durable facts, preferences, project decisions, and task learnings."
    )


def main() -> None:
    logger.info("Starting Mem0 self-hosted MCP bridge at %s:%s", server.settings.host, server.settings.port)
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
