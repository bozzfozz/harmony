from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from starlette.requests import Request

from app.errors import AppError, ErrorCode
from app.ui.services.dashboard import (
    DashboardHealthSummary,
    DashboardStatusSummary,
    DashboardUiService,
)


class _MockResponse:
    def __init__(
        self,
        *,
        status_code: int,
        json_data: Mapping[str, Any] | None,
        content: bytes | str | None,
        headers: Mapping[str, str] | None,
    ) -> None:
        self._status_code = status_code
        self._json = json_data
        self._content = content
        self._headers = headers

    def build(self, request: httpx.Request) -> httpx.Response:
        if self._json is not None:
            return httpx.Response(
                status_code=self._status_code,
                json=self._json,
                headers=self._headers,
                request=request,
            )
        content = self._content
        if isinstance(content, str):
            content = content.encode("utf-8")
        return httpx.Response(
            status_code=self._status_code,
            content=content or b"",
            headers=self._headers,
            request=request,
        )


class _HTTPXMock:
    def __init__(self) -> None:
        self._responses: dict[tuple[str, str], list[_MockResponse]] = {}
        self.requests: list[httpx.Request] = []

    def add_response(
        self,
        *,
        method: str = "GET",
        url: str,
        status_code: int = 200,
        json: Mapping[str, Any] | None = None,
        content: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if json is None and content is None:
            json = {}
        key = (method.upper(), str(httpx.URL(url)))
        response = _MockResponse(
            status_code=status_code,
            json_data=json,
            content=content,
            headers=headers,
        )
        self._responses.setdefault(key, []).append(response)

    def _resolve_response(self, method: str, url: str) -> _MockResponse:
        key = (method.upper(), url)
        queue = self._responses.get(key)
        if not queue:
            raise AssertionError(f"No response registered for {method} {url}")
        return queue.pop(0)

    def request(
        self,
        method: str,
        url: str,
        *,
        base_url: str | httpx.URL | None,
        headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        base = httpx.URL(str(base_url)) if base_url is not None else httpx.URL("")
        target = base.join(url)
        target_repr = str(target)
        request = httpx.Request(method.upper(), target, headers=headers)
        self.requests.append(request)
        response = self._resolve_response(method, target_repr)
        return response.build(request)


@pytest.fixture()
def httpx_mock(monkeypatch: pytest.MonkeyPatch) -> _HTTPXMock:
    mock = _HTTPXMock()

    class _PatchedAsyncClient:
        def __init__(self, *args: Any, base_url: Any = None, timeout: Any = None, **kwargs: Any) -> None:
            self._base_url = base_url
            self._timeout = timeout

        async def __aenter__(self) -> "_PatchedAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> httpx.Response:
            return mock.request("GET", url, base_url=self._base_url, headers=headers)

    monkeypatch.setattr(httpx, "AsyncClient", _PatchedAsyncClient)
    return mock


class _StubSecurityConfig:
    def __init__(self, *, require_auth: bool, api_keys: tuple[str, ...]) -> None:
        self._require_auth = require_auth
        self.api_keys = api_keys

    def resolve_require_auth(self) -> bool:
        return self._require_auth

    @property
    def require_auth(self) -> bool:
        return self._require_auth


def _make_request(
    *,
    security: _StubSecurityConfig | None = None,
    base_url: str = "http://testserver/",
    api_base_path: str = "/api",
) -> Request:
    url = httpx.URL(base_url)
    port = url.port or (443 if url.scheme == "https" else 80)
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/ui/dashboard",
        "root_path": "",
        "scheme": url.scheme,
        "server": (url.host, port),
        "headers": [],
        "query_string": b"",
    }
    state = SimpleNamespace()
    if api_base_path is not None:
        state.api_base_path = api_base_path
    if security is not None:
        state.security_config = security
    scope["app"] = SimpleNamespace(state=state)
    return Request(scope)


@pytest.mark.asyncio
async def test_fetch_status_parses_payload(httpx_mock: _HTTPXMock) -> None:
    payload = {
        "status": "healthy",
        "version": "1.2.3",
        "uptime_seconds": 42,
        "connections": {"redis": "down", "db": "up"},
        "readiness": {
            "status": "degraded",
            "issues": [
                {
                    "component": "redis",
                    "message": "timeout",
                    "exit_code": 1,
                    "details": {"attempts": 3},
                },
                {"component": "db", "message": "stale"},
            ],
        },
    }
    httpx_mock.add_response(url="http://testserver/api/status", json=payload)

    security = _StubSecurityConfig(require_auth=True, api_keys=("secret",))
    request = _make_request(security=security)
    service = DashboardUiService()

    summary = await service.fetch_status(request)

    assert isinstance(summary, DashboardStatusSummary)
    assert summary.status == "healthy"
    assert summary.version == "1.2.3"
    assert summary.uptime_seconds == 42.0
    assert summary.readiness_status == "degraded"
    assert [conn.name for conn in summary.connections] == ["db", "redis"]
    assert [conn.status for conn in summary.connections] == ["up", "down"]
    assert len(summary.readiness_issues) == 2
    assert httpx_mock.requests[0].headers["X-API-Key"] == "secret"


@pytest.mark.asyncio
async def test_fetch_workers_parses_payload(httpx_mock: _HTTPXMock) -> None:
    payload = {
        "status": "ok",
        "workers": {
            "alpha": {
                "status": "idle",
                "queue_size": 0,
                "last_seen": "2024-01-01T00:00:00Z",
                "component": "scheduler",
                "job": "sync",
            },
            "beta": {
                "status": "busy",
                "queue_size": 2,
                "last_seen": None,
                "component": None,
                "job": None,
            },
        },
    }
    httpx_mock.add_response(url="http://testserver/api/status", json=payload)

    request = _make_request()
    service = DashboardUiService()

    workers = await service.fetch_workers(request)

    assert len(workers) == 2
    assert workers[0].name == "alpha"
    assert workers[0].queue_size == 0
    assert workers[1].name == "beta"
    assert workers[1].queue_size == 2


@pytest.mark.asyncio
async def test_fetch_health_parses_payload(httpx_mock: _HTTPXMock) -> None:
    live_payload = {"status": "ok"}
    ready_payload = {
        "status": "warn",
        "checks": {"db": {"status": "ok"}},
        "issues": [
            {
                "component": "worker",
                "message": "delayed",
                "exit_code": 2,
                "details": {"queue": "beta"},
            }
        ],
    }
    httpx_mock.add_response(url="http://testserver/api/health/live", json=live_payload)
    httpx_mock.add_response(url="http://testserver/api/health/ready", status_code=503, json=ready_payload)

    request = _make_request()
    service = DashboardUiService()

    summary = await service.fetch_health(request)

    assert isinstance(summary, DashboardHealthSummary)
    assert summary.live_status == "ok"
    assert summary.ready_status == "warn"
    assert summary.ready_ok is False
    assert "db" in summary.checks
    assert len(summary.issues) == 1
    assert summary.issues[0].component == "worker"
    assert summary.issues[0].exit_code == 2


def test_resolve_base_url_and_headers_adds_api_key() -> None:
    service = DashboardUiService()
    security = _StubSecurityConfig(require_auth=True, api_keys=("primary", "secondary"))
    request = _make_request(security=security)

    base_url, headers = service._resolve_base_url_and_headers(request)

    assert base_url == "http://testserver/"
    assert headers["Accept"] == "application/json"
    assert headers["X-API-Key"] == "primary"


def test_resolve_base_url_and_headers_skips_api_key_when_not_required() -> None:
    service = DashboardUiService()
    security = _StubSecurityConfig(require_auth=False, api_keys=("primary",))
    request = _make_request(security=security)

    _, headers = service._resolve_base_url_and_headers(request)

    assert "X-API-Key" not in headers
    assert headers["Accept"] == "application/json"


def test_resolve_base_url_and_headers_raises_when_keys_missing() -> None:
    service = DashboardUiService()
    security = _StubSecurityConfig(require_auth=True, api_keys=())
    request = _make_request(security=security)

    with pytest.raises(AppError) as exc:
        service._resolve_base_url_and_headers(request)

    assert exc.value.code is ErrorCode.INTERNAL_ERROR


@pytest.mark.asyncio
async def test_fetch_status_raises_dependency_error_on_http_failure(httpx_mock: _HTTPXMock) -> None:
    httpx_mock.add_response(url="http://testserver/api/status", status_code=502, json={"error": "fail"})

    request = _make_request()
    service = DashboardUiService()

    with pytest.raises(AppError) as exc:
        await service.fetch_status(request)

    assert exc.value.code is ErrorCode.DEPENDENCY_ERROR
    assert exc.value.http_status == 502


@pytest.mark.asyncio
async def test_fetch_status_raises_when_json_invalid(httpx_mock: _HTTPXMock) -> None:
    httpx_mock.add_response(url="http://testserver/api/status", content="not-json")

    request = _make_request()
    service = DashboardUiService()

    with pytest.raises(AppError) as exc:
        await service.fetch_status(request)

    assert exc.value.code is ErrorCode.DEPENDENCY_ERROR


@pytest.mark.asyncio
async def test_fetch_health_raises_when_live_unexpected(httpx_mock: _HTTPXMock) -> None:
    httpx_mock.add_response(url="http://testserver/api/health/live", status_code=404, json={})
    httpx_mock.add_response(url="http://testserver/api/health/ready", json={"status": "ok"})

    request = _make_request()
    service = DashboardUiService()

    with pytest.raises(AppError) as exc:
        await service.fetch_health(request)

    assert exc.value.code is ErrorCode.DEPENDENCY_ERROR
    assert exc.value.http_status == 404
