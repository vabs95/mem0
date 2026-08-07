from __future__ import annotations

import os
from typing import Any

import functools

import httpx


@functools.lru_cache(maxsize=8)
def _pooled_client(api_url: str, timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout)


class Mem0SelfHostedClient:
    def __init__(self, api_url: str, api_key: str = "", timeout: float = 15.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "Mem0SelfHostedClient":
        api_url = os.environ.get("MEM0_API_URL", "http://mem0:8000")
        api_key = os.environ.get("MEM0_API_KEY") or os.environ.get("ADMIN_API_KEY", "")
        return cls(api_url=api_url, api_key=api_key)

    def with_api_key(self, api_key: str) -> "Mem0SelfHostedClient":
        """Return a new client instance using a different API key."""
        return Mem0SelfHostedClient(api_url=self.api_url, api_key=api_key, timeout=self.timeout)

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        # Reuse one connection-pooled client per (api_url, timeout) pair
        # instead of opening a fresh TCP/TLS connection for every tool
        # call -- with_api_key() creates a new instance per request (one
        # per distinct caller identity), so pooling has to be keyed rather
        # than per-instance to actually help.
        response = _pooled_client(self.api_url, self.timeout).request(
            method,
            f"{self.api_url}{path}",
            headers=self.headers,
            json=json_body,
            params={k: v for k, v in (params or {}).items() if v is not None},
        )
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


def _flatten_filters(value: Any) -> Any:
    """Recursively reshape cloud-style filters into the flat dict the
    self-hosted backend expects.

    Calling agents send the same filter shapes here as they do to the
    hosted platform API: ``{"AND": [{"user_id": "x"}, {"metadata": {"type":
    "y"}}]}``. Self-hosted stores every scoping/metadata field flat on the
    payload -- there's no logical-operator support and no "metadata" field
    to nest under -- so an AND clause has to collapse to a flat dict, a
    nested "metadata" dict has to lift to top-level keys, and "app_id" (the
    hosted-API name for this same concept) has to become "project". None of
    this errors on its own; it just silently matches nothing, so it has to
    be handled before the request reaches the backend, not after a 400 or
    an empty result comes back.
    """
    if not isinstance(value, dict):
        if isinstance(value, list):
            return [_flatten_filters(item) for item in value]
        return value

    flat: dict[str, Any] = {}
    if "AND" in value and isinstance(value["AND"], list):
        for item in value["AND"]:
            if isinstance(item, dict):
                flat.update(item)
        for k, v in value.items():
            if k not in ("AND", "OR", "NOT"):
                flat[k] = v
    else:
        flat = value

    mapped: dict[str, Any] = {}
    for key, item in flat.items():
        if key == "metadata" and isinstance(item, dict):
            for mk, mv in item.items():
                mapped[mk] = _flatten_filters(mv)
            continue
        mapped["project" if key == "app_id" else key] = _flatten_filters(item)
    return mapped


def build_filters(
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    project: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a flat filters dict that the self-hosted backend expects.

    Entity IDs (user_id, agent_id, run_id) go at the top level.
    The optional ``project`` key is also placed at the top level so
    the vector store can filter on it as a metadata field.
    ``extra`` -- typically the calling agent's own ``filters`` tool
    argument, in whatever cloud-style shape it chose -- is flattened via
    _flatten_filters before being merged in.
    """
    filters: dict[str, Any] = {}
    if user_id:
        filters["user_id"] = user_id
    if agent_id:
        filters["agent_id"] = agent_id
    if run_id:
        filters["run_id"] = run_id
    if project:
        filters["project"] = project
    if extra:
        filters.update(_flatten_filters(extra))
    return filters
