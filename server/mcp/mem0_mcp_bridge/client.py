from __future__ import annotations

import os
from typing import Any

import httpx


class Mem0SelfHostedClient:
    def __init__(self, api_url: str, api_key: str, timeout: float = 15.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "Mem0SelfHostedClient":
        api_url = os.environ.get("MEM0_API_URL", "http://mem0:8000")
        api_key = os.environ.get("MEM0_API_KEY") or os.environ.get("ADMIN_API_KEY", "")
        return cls(api_url=api_url, api_key=api_key)

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


def app_id_to_agent_id(payload: dict[str, Any]) -> dict[str, Any]:
    mapped = dict(payload)
    app_id = mapped.pop("app_id", None)
    if app_id and not mapped.get("agent_id"):
        mapped["agent_id"] = app_id
    return mapped


def app_filters_to_agent_filters(value: Any) -> Any:
    if isinstance(value, list):
        return [app_filters_to_agent_filters(item) for item in value]
    if not isinstance(value, dict):
        return value
    mapped: dict[str, Any] = {}
    for key, item in value.items():
        mapped["agent_id" if key == "app_id" else key] = app_filters_to_agent_filters(item)
    return mapped


def default_user_filter(default_user_id: str, filters: dict[str, Any] | None) -> dict[str, Any]:
    if not filters:
        return {"AND": [{"user_id": default_user_id}]}
    text = str(filters)
    if "user_id" in text or "agent_id" in text or "run_id" in text or "app_id" in text:
        return app_filters_to_agent_filters(filters)
    if not any(key in filters for key in ("AND", "OR", "NOT")):
        filters = {"AND": [filters]}
    filters = app_filters_to_agent_filters(filters)
    filters.setdefault("AND", []).insert(0, {"user_id": default_user_id})
    return filters
