from __future__ import annotations

from typing import Any

import httpx

from vps_deployer.core.config import Settings, get_settings


class ApiUnavailableError(RuntimeError):
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        super().__init__(
            f"VPS Deployer API is not reachable at {base_url}. "
            "Start the service or run: "
            "uv run uvicorn vps_deployer.api.main:app --host 127.0.0.1 --port 5100"
        )


class ApiRequestError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(message)


def _detail(payload: object) -> str:
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            parts: list[str] = []
            for item in detail:
                if isinstance(item, dict) and "msg" in item:
                    parts.append(str(item["msg"]))
                else:
                    parts.append(str(item))
            return "; ".join(parts) if parts else "Request failed"
    return "Request failed"


def api_request(
    method: str,
    path: str,
    json: dict[str, Any] | None = None,
    settings: Settings | None = None,
    timeout: float = 2.0,
) -> dict[str, object]:
    current = settings or get_settings()
    url = f"{current.api_base_url}{path}"
    try:
        response = httpx.request(method, url, json=json, timeout=timeout)
    except httpx.HTTPError as exc:
        raise ApiUnavailableError(current.api_base_url) from exc
    if response.status_code >= 400:
        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        raise ApiRequestError(_detail(payload), response.status_code)
    if response.status_code == 204 or not response.content:
        return {}
    try:
        body = response.json()
    except ValueError as exc:
        raise ApiUnavailableError(current.api_base_url) from exc
    if not isinstance(body, dict):
        raise ApiUnavailableError(current.api_base_url)
    return body


def api_get(path: str, settings: Settings | None = None, timeout: float = 2.0) -> dict[str, object]:
    return api_request("GET", path, settings=settings, timeout=timeout)
