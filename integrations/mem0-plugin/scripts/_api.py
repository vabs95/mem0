"""Mem0 REST compatibility helpers for plugin hooks.

Cloud remains the default. Set ``MEM0_API_MODE=self_hosted`` and
``MEM0_API_URL`` to target the self-hosted FastAPI server.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

CLOUD_API_URL = "https://api.mem0.ai"


def api_mode() -> str:
    raw = os.environ.get("MEM0_API_MODE", "cloud").strip().lower().replace("-", "_")
    return "self_hosted" if raw in {"self_hosted", "selfhosted", "self"} else "cloud"


def api_base_url() -> str:
    return os.environ.get("MEM0_API_URL", CLOUD_API_URL).rstrip("/")


def auth_headers(api_key: str) -> dict[str, str]:
    if api_mode() == "self_hosted":
        header = os.environ.get("MEM0_AUTH_HEADER", "X-API-Key")
        return {header: api_key}
    return {"Authorization": f"Token {api_key}"}


def _request_json(
    api_key: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: int = 15,
) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", **auth_headers(api_key)}
    req = urllib.request.Request(f"{api_base_url()}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if not raw:
            return resp.status, {}
        if not isinstance(raw, (bytes, bytearray, str)):
            return resp.status, {}
        return resp.status, json.loads(raw)


def _self_hosted_body(body: dict[str, Any]) -> dict[str, Any]:
    mapped = dict(body)
    app_id = mapped.pop("app_id", None)
    if app_id and not mapped.get("agent_id"):
        mapped["agent_id"] = app_id
    return mapped


def _self_hosted_filters(value: Any) -> Any:
    if not isinstance(value, dict):
        if isinstance(value, list):
            return [_self_hosted_filters(item) for item in value]
        return value

    # Flatten AND clauses if present to support flat backend filters
    flat: dict[str, Any] = {}
    if "AND" in value and isinstance(value["AND"], list):
        for item in value["AND"]:
            if isinstance(item, dict):
                for k, v in item.items():
                    flat[k] = v
        # Also include any other top-level keys that aren't logical operators
        for k, v in value.items():
            if k not in ("AND", "OR", "NOT"):
                flat[k] = v
    else:
        flat = value

    mapped: dict[str, Any] = {}
    for key, item in flat.items():
        mapped["agent_id" if key == "app_id" else key] = _self_hosted_filters(item)
    return mapped


def add_memory(api_key: str, body: dict[str, Any], timeout: int = 15) -> tuple[int, Any]:
    path = "/memories" if api_mode() == "self_hosted" else "/v3/memories/add/"
    if api_mode() == "self_hosted":
        body = _self_hosted_body(body)
    return _request_json(api_key, path, method="POST", body=body, timeout=timeout)


def search_memories(api_key: str, body: dict[str, Any], timeout: int = 5) -> tuple[int, Any]:
    path = "/search" if api_mode() == "self_hosted" else "/v3/memories/search/"
    if api_mode() == "self_hosted" and "limit" in body and "top_k" not in body:
        body = {**body, "top_k": body["limit"]}
    if api_mode() == "self_hosted" and "filters" in body:
        body = {**body, "filters": _self_hosted_filters(body["filters"])}
    return _request_json(api_key, path, method="POST", body=body, timeout=timeout)


def list_memories(api_key: str, body: dict[str, Any], timeout: int = 5) -> tuple[int, Any]:
    if api_mode() == "self_hosted":
        filters = _self_hosted_filters(body.get("filters") or {})
        params: dict[str, Any] = {}
        for key in ("user_id", "agent_id", "run_id"):
            if key in filters and isinstance(filters[key], str) and filters[key] != "*":
                params[key] = filters[key]
        if "page_size" in body:
            params["top_k"] = body["page_size"]
        elif "top_k" in body:
            params["top_k"] = body["top_k"]
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        return _request_json(api_key, f"/memories{query}", method="GET", timeout=timeout)

    page = body.get("page", 1)
    page_size = body.get("page_size") or body.get("top_k") or 10
    return _request_json(
        api_key,
        f"/v3/memories/?page={page}&page_size={page_size}",
        method="POST",
        body={"filters": body.get("filters", {})},
        timeout=timeout,
    )


def delete_memory(api_key: str, memory_id: str, timeout: int = 10) -> tuple[int, Any]:
    if api_mode() == "self_hosted":
        return _request_json(api_key, f"/memories/{memory_id}", method="DELETE", timeout=timeout)
    return _request_json(api_key, f"/v1/memories/{memory_id}/", method="DELETE", timeout=timeout)
