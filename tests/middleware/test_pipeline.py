from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
import pytest

from app.config import load_config
from app.middleware import install_middleware


def _build_app(monkeypatch: pytest.MonkeyPatch, env: dict[str, str] | None = None) -> FastAPI:
    if env:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
    config = load_config()
    app = FastAPI()
    install_middleware(app, config)
    return app


def test_logging_emits_api_request_event(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_log_event(logger: Any, event: str, **payload: Any) -> None:  # type: ignore[override]
        captured.append((event, payload))

    monkeypatch.setenv("CACHEABLE_PATHS", "")
    monkeypatch.delenv("FEATURE_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("FEATURE_RATE_LIMITING", raising=False)
    monkeypatch.setenv("REQUEST_ID_HEADER", "X-Request-ID")
    monkeypatch.setattr("app.middleware.logging.log_event", fake_log_event)

    app = _build_app(monkeypatch)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    response = client.get("/ping")
    assert response.status_code == 200

    api_events = [payload for event, payload in captured if event == "api.request"]
    assert api_events, "expected at least one api.request event"
    event_payload = api_events[-1]
    assert event_payload["path"] == "/ping"
    assert event_payload["method"] == "GET"
    assert event_payload["status_code"] == 200
    assert isinstance(event_payload["duration_ms"], (int, float))


def test_auth_apikey_allows_valid_and_blocks_invalid_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_REQUIRE_AUTH", "true")
    monkeypatch.setenv("HARMONY_API_KEYS", "valid-key")
    monkeypatch.setenv("CACHEABLE_PATHS", "")
    app = _build_app(monkeypatch)

    @app.get("/secure")
    async def secure() -> dict[str, str]:
        return {"status": "secure"}

    client = TestClient(app)
    missing = client.get("/secure")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "INTERNAL_ERROR"

    valid = client.get("/secure", headers={"Authorization": "ApiKey valid-key"})
    assert valid.status_code == 200
    assert valid.json()["status"] == "secure"

    forbidden = client.get("/secure", headers={"Authorization": "ApiKey nope"})
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "INTERNAL_ERROR"


def test_rate_limit_disabled_by_default_and_enforced_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FEATURE_RATE_LIMITING", raising=False)
    monkeypatch.setenv("CACHEABLE_PATHS", "")
    app = _build_app(monkeypatch)

    @app.get("/limited")
    async def limited() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    first = client.get("/limited")
    second = client.get("/limited")
    assert first.status_code == 200
    assert second.status_code == 200

    monkeypatch.setenv("FEATURE_RATE_LIMITING", "true")
    monkeypatch.setenv("RATE_LIMIT_BUCKET_CAP", "1")
    monkeypatch.setenv("RATE_LIMIT_REFILL_PER_SEC", "0")
    app_limited = _build_app(monkeypatch)

    @app_limited.get("/limited")
    async def limited_active() -> dict[str, str]:
        return {"status": "ok"}

    limited_client = TestClient(app_limited)
    assert limited_client.get("/limited").status_code == 200
    denied = limited_client.get("/limited")
    assert denied.status_code == 429
    body = denied.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in denied.headers


def test_cache_etag_304_on_match_and_200_on_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("CACHEABLE_PATHS", "/cache/me")
    monkeypatch.setenv("FEATURE_REQUIRE_AUTH", "false")
    app = _build_app(monkeypatch)

    @app.get("/cache/me")
    async def cached(value: int = Query(..., ge=0)) -> dict[str, int]:
        return {"value": value}

    client = TestClient(app)

    first = client.get("/cache/me", params={"value": 1})
    assert first.status_code == 200
    etag = first.headers.get("etag")
    assert etag

    cached_response = client.get(
        "/cache/me",
        params={"value": 1},
        headers={"If-None-Match": etag},
    )
    assert cached_response.status_code == 304

    changed = client.get(
        "/cache/me",
        params={"value": 2},
        headers={"If-None-Match": etag},
    )
    assert changed.status_code == 200
    assert changed.json()["value"] == 2
    assert changed.headers.get("etag") != etag


def test_error_mapping_validation_and_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHEABLE_PATHS", "")
    app = _build_app(monkeypatch)

    @app.get("/validate")
    async def validate_endpoint(required: int = Query(...)) -> dict[str, int]:
        return {"value": required}

    @app.get("/dependency")
    async def dependency_endpoint() -> None:
        raise HTTPException(status_code=503, detail="Upstream down")

    client = TestClient(app)

    validation = client.get("/validate", params={"required": "bad"})
    assert validation.status_code == 422
    body = validation.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"

    dependency = client.get("/dependency")
    assert dependency.status_code == 503
    dependency_body = dependency.json()
    assert dependency_body["error"]["code"] == "DEPENDENCY_ERROR"


def test_cors_and_gzip_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://example.com")
    monkeypatch.setenv("CORS_ALLOWED_HEADERS", "X-Test-Header")
    monkeypatch.setenv("CORS_ALLOWED_METHODS", "GET")
    monkeypatch.setenv("GZIP_MIN_SIZE", "8")
    monkeypatch.setenv("CACHEABLE_PATHS", "")
    app = _build_app(monkeypatch)

    payload = "x" * 64

    @app.get("/cors-gzip", response_class=PlainTextResponse)
    async def cors_route() -> str:
        return payload

    client = TestClient(app)

    cors_response = client.options(
        "/cors-gzip",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Test-Header",
        },
    )
    assert cors_response.headers.get("access-control-allow-origin") == "http://example.com"
    assert "X-Test-Header" in cors_response.headers.get("access-control-allow-headers", "")

    gzip_response = client.get(
        "/cors-gzip",
        headers={"Accept-Encoding": "gzip"},
    )
    assert gzip_response.status_code == 200
    assert gzip_response.headers.get("content-encoding") == "gzip"
    assert gzip_response.text == payload
