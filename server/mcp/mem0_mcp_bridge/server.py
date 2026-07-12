from __future__ import annotations

import contextvars
import json
import logging
import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.types import ASGIApp, Receive, Scope, Send

from .client import Mem0SelfHostedClient, build_filters

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("mem0_mcp_bridge")

# ---------------------------------------------------------------------------
# Defaults from env (used as fallback when headers are absent)
# ---------------------------------------------------------------------------
DEFAULT_USER_ID = os.environ.get("MEM0_DEFAULT_USER_ID", "mem0-mcp")
DEFAULT_AGENT_ID = os.environ.get("MEM0_DEFAULT_AGENT_ID", "")

# ---------------------------------------------------------------------------
# Context variables – populated per-request by ASGI middleware
# ---------------------------------------------------------------------------
_request_api_key: contextvars.ContextVar[str] = contextvars.ContextVar("_request_api_key", default="")
_request_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("_request_user_id", default="")
_request_source_agent: contextvars.ContextVar[str] = contextvars.ContextVar("_request_source_agent", default="")


class _HeaderMiddleware:
    """ASGI middleware that extracts per-client identity from HTTP headers.

    Headers read:
      - ``Authorization: Bearer <key>``  → forwarded to the backend as API key
      - ``X-User-Id``                    → scopes memories to this user
      - ``X-Source-Agent``               → auto-tagged on writes (provenance)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            # Extract Bearer token or raw API key
            auth = headers.get(b"authorization", b"").decode().strip()
            if auth:
                if auth.lower().startswith("bearer "):
                    _request_api_key.set(auth[7:].strip())
                else:
                    _request_api_key.set(auth)
            # Extract identity headers
            user_id = headers.get(b"x-user-id", b"").decode().strip()
            if user_id:
                _request_user_id.set(user_id)
            source = headers.get(b"x-source-agent", b"").decode().strip()
            if source:
                _request_source_agent.set(source)
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_call(func, *args, **kwargs) -> str:
    try:
        return json.dumps(func(*args, **kwargs), ensure_ascii=False)
    except Exception as exc:
        logger.exception("Mem0 MCP bridge call failed")
        return json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False)


_base_client = Mem0SelfHostedClient.from_env()


def _client() -> Mem0SelfHostedClient:
    """Return a client using the per-request Bearer token if present,
    otherwise fall back to the env-configured API key."""
    api_key = _request_api_key.get()
    if api_key:
        return _base_client.with_api_key(api_key)
    return _base_client


def _effective_user_id(user_id: str | None) -> str:
    """Resolve the user_id: explicit arg > header > env default."""
    return user_id or _request_user_id.get() or DEFAULT_USER_ID


def _effective_agent_id(agent_id: str | None) -> str | None:
    """Resolve the agent_id: explicit arg > header > env default."""
    return agent_id or _request_source_agent.get() or DEFAULT_AGENT_ID or None


def _source_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Inject ``source`` into metadata from the X-Source-Agent header."""
    source = _request_source_agent.get()
    if not source:
        return metadata or {}
    result = dict(metadata) if metadata else {}
    result.setdefault("source", source)
    return result


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

server = FastMCP(
    "mem0",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8765")),
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@server.tool(description="Store a new preference, fact, or conversation snippet.")
def add_memory(
    text: Annotated[str | None, Field(default=None, description="Plain sentence summarizing what to store.")] = None,
    messages: Annotated[list[dict[str, str]] | None, Field(default=None, description="Role/content messages.")] = None,
    user_id: Annotated[str | None, Field(default=None, description="User scope (default: from config header).")] = None,
    agent_id: Annotated[
        str | None, Field(default=None, description="Agent scope (default: from config header).")
    ] = None,
    run_id: Annotated[str | None, Field(default=None, description="Run/session scope.")] = None,
    project: Annotated[
        str | None, Field(default=None, description="Project scope. Stored in metadata for filtering.")
    ] = None,
    metadata: Annotated[dict[str, Any] | None, Field(default=None, description="Metadata JSON.")] = None,
    infer: Annotated[bool, Field(default=True, description="Whether Mem0 should extract facts.")] = True,
) -> str:
    if not messages:
        if not text:
            return json.dumps({"error": "messages_missing", "detail": "Provide text or messages."})
        messages = [{"role": "user", "content": text}]

    effective_metadata = _source_metadata(metadata)
    if project:
        effective_metadata["project"] = project

    payload: dict[str, Any] = {
        "messages": messages,
        "user_id": _effective_user_id(user_id),
        "agent_id": _effective_agent_id(agent_id),
        "run_id": run_id,
        "metadata": effective_metadata or None,
        "infer": infer,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    return _json_call(_client().request, "POST", "/memories", json_body=payload)


@server.tool(description="Run a semantic search over existing memories.")
def search_memories(
    query: Annotated[str, Field(description="Natural language search query.")],
    user_id: Annotated[str | None, Field(default=None, description="User scope (default: from config header).")] = None,
    agent_id: Annotated[str | None, Field(default=None, description="Agent scope.")] = None,
    run_id: Annotated[str | None, Field(default=None, description="Run scope.")] = None,
    project: Annotated[str | None, Field(default=None, description="Filter by project.")] = None,
    filters: Annotated[dict[str, Any] | None, Field(default=None, description="Additional structured filters.")] = None,
    top_k: Annotated[int | None, Field(default=None, description="Maximum results.")] = None,
    threshold: Annotated[float | None, Field(default=None, description="Minimum similarity score.")] = None,
) -> str:
    search_filters = build_filters(
        user_id=_effective_user_id(user_id),
        agent_id=agent_id,
        run_id=run_id,
        project=project,
        extra=filters,
    )
    payload: dict[str, Any] = {
        "query": query,
        "filters": search_filters,
        "top_k": top_k,
        "threshold": threshold,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    return _json_call(_client().request, "POST", "/search", json_body=payload)


@server.tool(description="List memories using structured filters.")
def get_memories(
    user_id: Annotated[str | None, Field(default=None, description="User scope (default: from config header).")] = None,
    agent_id: Annotated[str | None, Field(default=None, description="Agent scope.")] = None,
    run_id: Annotated[str | None, Field(default=None, description="Run scope.")] = None,
    project: Annotated[str | None, Field(default=None, description="Filter by project.")] = None,
    top_k: Annotated[int | None, Field(default=None, description="Maximum memories to list.")] = None,
) -> str:
    params: dict[str, Any] = {
        "user_id": _effective_user_id(user_id),
        "top_k": top_k,
    }
    if agent_id:
        params["agent_id"] = agent_id
    if run_id:
        params["run_id"] = run_id
    # Note: project filtering on GET /memories is not supported by the backend
    # query params; agent should use search_memories with project filter instead.
    return _json_call(_client().request, "GET", "/memories", params=params)


@server.tool(description="Fetch a single memory by ID.")
def get_memory(memory_id: Annotated[str, Field(description="Memory ID.")]) -> str:
    return _json_call(_client().request, "GET", f"/memories/{memory_id}")


@server.tool(description="Overwrite an existing memory's text.")
def update_memory(
    memory_id: Annotated[str, Field(description="Memory ID.")],
    text: Annotated[str, Field(description="Replacement memory text.")],
    metadata: Annotated[
        dict[str, Any] | None, Field(default=None, description="Optional replacement metadata.")
    ] = None,
) -> str:
    payload: dict[str, Any] = {"text": text}
    if metadata is not None:
        payload["metadata"] = metadata
    return _json_call(_client().request, "PUT", f"/memories/{memory_id}", json_body=payload)


@server.tool(description="Delete one memory by ID.")
def delete_memory(memory_id: Annotated[str, Field(description="Memory ID.")]) -> str:
    return _json_call(_client().request, "DELETE", f"/memories/{memory_id}")


@server.tool(description="Delete every memory in a user/agent/run scope.")
def delete_all_memories(
    user_id: Annotated[str | None, Field(default=None, description="User scope (default: from config header).")] = None,
    agent_id: Annotated[str | None, Field(default=None, description="Agent scope.")] = None,
    run_id: Annotated[str | None, Field(default=None, description="Run scope.")] = None,
) -> str:
    params: dict[str, Any] = {
        "user_id": _effective_user_id(user_id),
    }
    if agent_id:
        params["agent_id"] = agent_id
    if run_id:
        params["run_id"] = run_id
    return _json_call(_client().request, "DELETE", "/memories", params=params)


@server.tool(description="List users, agents, and runs currently holding memories.")
def list_entities() -> str:
    return _json_call(_client().request, "GET", "/entities")


@server.tool(description="Delete a user/agent/run entity and its memories.")
def delete_entities(
    user_id: Annotated[str | None, Field(default=None, description="User entity to delete.")] = None,
    agent_id: Annotated[str | None, Field(default=None, description="Agent entity to delete.")] = None,
    run_id: Annotated[str | None, Field(default=None, description="Run entity to delete.")] = None,
) -> str:
    scopes = [(k[:-3], v) for k, v in {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}.items() if v]
    if len(scopes) != 1:
        return json.dumps({"error": "scope_invalid", "detail": "Provide exactly one of user_id, agent_id, or run_id."})
    entity_type, entity_id = scopes[0]
    return _json_call(_client().request, "DELETE", f"/entities/{entity_type}/{entity_id}")


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


@server.prompt()
def memory_assistant() -> str:
    return (
        "You have access to Mem0 tools for long-term memory. "
        "Memories are scoped by user_id (the human), agent_id (the AI agent), "
        "and optionally by project (stored in metadata) and run_id (task/session). "
        "Use the 'project' parameter to organize memories by project/workspace. "
        "Store durable facts, preferences, project decisions, and task learnings."
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    logger.info("Starting Mem0 self-hosted MCP bridge at %s:%s", server.settings.host, server.settings.port)
    # Wrap the ASGI app with header-extraction middleware
    original_app = server.streamable_http_app()
    wrapped_app = _HeaderMiddleware(original_app)
    # Replace the method so the server uses our wrapped app
    server.streamable_http_app = lambda: wrapped_app  # type: ignore[method-assign]
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
