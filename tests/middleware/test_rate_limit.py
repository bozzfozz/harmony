"""Tests for the rate limiting middleware behaviour."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
import pytest

from app.config import RateLimitMiddlewareConfig, SecurityConfig
from app.middleware.rate_limit import RateLimitMiddleware


@dataclass(slots=True)
class _StubRateLimiter:
    _max_requests: int
    _window_seconds: int


def _security_config(*, allowlist: tuple[str, ...] = ()) -> SecurityConfig:
    return SecurityConfig(
        profile="test",
        api_keys=(),
        allowlist=allowlist,
        allowed_origins=(),
        _require_auth_default=False,
        _rate_limiting_default=True,
        ui_cookies_secure=False,
    )


def _get_security_config() -> SecurityConfig:
    return _security_config()


def _get_rate_limiter() -> _StubRateLimiter | None:
    return None


_RATE_LIMIT_CONFIG = RateLimitMiddlewareConfig(
    enabled=True,
    bucket_capacity=1,
    refill_per_second=0.0,
)


def _apply_overrides(app: FastAPI) -> None:
    security_dependency = app.dependency_overrides.get(_get_security_config, _get_security_config)
    rate_limiter_dependency = app.dependency_overrides.get(_get_rate_limiter, _get_rate_limiter)
    app.state.security_config = security_dependency()
    app.state.rate_limiter = rate_limiter_dependency()


def _create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/limited")
    async def _limited() -> dict[str, bool]:  # pragma: no cover - exercised via tests
        return {"ok": True}

    @app.get("/allowlisted")
    async def _allowlisted() -> dict[str, bool]:  # pragma: no cover - exercised via tests
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        config=_RATE_LIMIT_CONFIG,
        security=_get_security_config(),
    )
    _apply_overrides(app)
    return app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_allowlisted_paths_bypass_rate_limits() -> None:
    app = _create_app()
    app.dependency_overrides[_get_security_config] = lambda: _security_config(
        allowlist=("/allowlisted",)
    )
    _apply_overrides(app)

    with TestClient(app) as client:
        responses = [client.get("/allowlisted") for _ in range(3)]

    for response in responses:
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert "Retry-After" not in response.headers


def test_rate_limited_requests_include_retry_after_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.middleware.rate_limit.time.monotonic", lambda: 100.0)

    app = _create_app()
    app.dependency_overrides[_get_rate_limiter] = lambda: _StubRateLimiter(
        _max_requests=2,
        _window_seconds=4,
    )
    _apply_overrides(app)

    with TestClient(app) as client:
        first = client.get("/limited")
        second = client.get("/limited")
        limited = client.get("/limited")

    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429

    payload = limited.json()
    assert payload == {
        "ok": False,
        "error": {
            "code": "RATE_LIMITED",
            "message": "Too many requests.",
            "meta": {"retry_after_ms": 2000},
        },
    }
    assert limited.headers["Retry-After"] == "2"
    assert "X-Debug-Id" in limited.headers


@pytest.mark.anyio
async def test_concurrent_requests_share_bucket_identity() -> None:
    app = _create_app()
    _apply_overrides(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first, second = await asyncio.gather(
            client.get("/limited"),
            client.get("/limited"),
        )

    if first.status_code == 429:
        limited_response, allowed_response = first, second
    else:
        limited_response, allowed_response = second, first

    assert allowed_response.status_code == 200
    assert allowed_response.json() == {"ok": True}

    assert limited_response.status_code == 429
    limited_payload = limited_response.json()
    assert limited_payload["error"]["code"] == "RATE_LIMITED"
    assert "meta" not in limited_payload["error"]
    assert limited_response.headers["Retry-After"] == "1"
