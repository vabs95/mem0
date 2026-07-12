from __future__ import annotations

import os
from typing import Any

import httpx


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
        with httpx.Client(timeout=self.timeout) as client:
            response = client.request(
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
    Any ``extra`` filters are merged in as well.
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
        filters.update(extra)
    return filters
