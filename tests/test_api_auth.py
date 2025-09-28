from __future__ import annotations

import pytest

from app import dependencies as deps
from app.main import app
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient


@pytest.fixture(autouse=True)
def configure_security(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARMONY_API_KEYS", "valid-key,rotating-key")
    monkeypatch.setenv("FEATURE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.local")
    monkeypatch.delenv("AUTH_ALLOWLIST", raising=False)
    deps.get_app_config.cache_clear()
    app.openapi_schema = None
    yield
    deps.get_app_config.cache_clear()
    app.openapi_schema = None


def test_request_without_key_returns_401() -> None:
    with SimpleTestClient(app, include_env_api_key=False) as client:
        response = client.get("/")

    assert response.status_code == 401
    body = response.json()
    assert body == {
        "ok": False,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An API key is required to access this resource.",
        },
    }
    debug_header = response.headers.get("X-Debug-Id") or response.headers.get("x-debug-id")
    assert debug_header is not None


def test_invalid_key_returns_403() -> None:
    with SimpleTestClient(
        app,
        default_headers={"X-API-Key": "invalid"},
        include_env_api_key=False,
    ) as client:
        response = client.get("/")

    assert response.status_code == 403
    body = response.json()
    assert body == {
        "ok": False,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "The provided API key is not valid.",
        },
    }
    debug_header = response.headers.get("X-Debug-Id") or response.headers.get("x-debug-id")
    assert debug_header is not None


def test_allowlist_path_bypasses_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ALLOWLIST", api_path("/health"))
    deps.get_app_config.cache_clear()
    app.openapi_schema = None

    with SimpleTestClient(app, include_env_api_key=False) as client:
        response = client.get("/health/spotify")

    assert response.status_code == 200


def test_bearer_header_supported() -> None:
    with SimpleTestClient(app, include_env_api_key=False) as client:
        response = client.get("/", headers={"Authorization": "Bearer valid-key"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_cors_preflight_skips_auth() -> None:
    with SimpleTestClient(app, include_env_api_key=False) as client:
        response = client.options(
            "/spotify/playlists",
            headers={
                "Origin": "https://app.local",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )

    assert response.status_code in {200, 204}


def test_openapi_declares_api_key_security() -> None:
    schema = app.openapi()

    assert "ApiKeyAuth" in schema["components"]["securitySchemes"]
    assert schema["security"] == [{"ApiKeyAuth": []}]
    health_get = schema["paths"][api_path("/health/spotify")]["get"]
    assert "security" not in health_get
