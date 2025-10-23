"""Tests for the ``require_api_key`` dependency."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.dependencies as dependencies_module
from app.config import SecurityConfig
from app.dependencies import require_api_key
from app.middleware.errors import setup_exception_handlers


def _security_config(*, api_keys: tuple[str, ...]) -> SecurityConfig:
    return SecurityConfig(
        profile="test",
        api_keys=api_keys,
        allowlist=(),
        allowed_origins=(),
        _require_auth_default=True,
        _rate_limiting_default=False,
        ui_cookies_secure=False,
    )


def _create_app(monkeypatch: pytest.MonkeyPatch, security: SecurityConfig) -> FastAPI:
    app = FastAPI()
    setup_exception_handlers(app)

    config = SimpleNamespace(security=security)

    def _get_app_config() -> SimpleNamespace:
        return config

    monkeypatch.setattr(dependencies_module, "get_app_config", _get_app_config)

    @app.get("/protected")
    def _protected(_: None = Depends(require_api_key)) -> dict[str, bool]:  # pragma: no cover - exercised in tests
        return {"ok": True}

    return app


def test_missing_api_key_returns_auth_required(monkeypatch: pytest.MonkeyPatch) -> None:
    security = _security_config(api_keys=("primary",))
    app = _create_app(monkeypatch, security)

    with TestClient(app) as client:
        response = client.get("/protected")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "APIKey"
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "AUTH_REQUIRED",
            "message": "An API key is required to access this resource.",
        },
    }


def test_invalid_api_key_returns_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    security = _security_config(api_keys=("primary",))
    app = _create_app(monkeypatch, security)

    with TestClient(app) as client:
        response = client.get("/protected", headers={"X-API-Key": "secondary"})

    assert response.status_code == 403
    assert "WWW-Authenticate" not in response.headers
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "AUTH_REQUIRED",
            "message": "The provided API key is not valid.",
        },
    }

