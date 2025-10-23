from __future__ import annotations

import logging
from collections.abc import Mapping

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config import SecurityConfig
from app.middleware.auth_apikey import ApiKeyAuthMiddleware


def _security_config(
    *,
    require_auth_default: bool,
    api_keys: tuple[str, ...],
    allowlist: tuple[str, ...] = (),
    require_auth_override: bool | None = None,
) -> SecurityConfig:
    return SecurityConfig(
        profile="test",
        api_keys=api_keys,
        allowlist=allowlist,
        allowed_origins=(),
        _require_auth_default=require_auth_default,
        _rate_limiting_default=False,
        ui_cookies_secure=False,
        _require_auth_override=require_auth_override,
    )


def _create_app(
    *,
    security: SecurityConfig,
    override_security: SecurityConfig | None = None,
) -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    def _protected(
        request: Request,
    ) -> Mapping[str, str | None]:  # pragma: no cover - exercised by tests
        return {"api_key": getattr(request.state, "api_key", None)}

    @app.get("/public")
    def _public() -> Mapping[str, bool]:  # pragma: no cover - exercised by tests
        return {"ok": True}

    app.add_middleware(ApiKeyAuthMiddleware, security=security)
    if override_security is not None:
        app.state.security_config = override_security
    return app


def test_requests_allowed_when_authentication_disabled() -> None:
    security = _security_config(require_auth_default=False, api_keys=("secret-key",))
    app = _create_app(security=security)

    with TestClient(app) as client:
        response = client.get("/protected")

    assert response.status_code == 200
    assert response.json() == {"api_key": None}


def test_allowlisted_paths_bypass_authentication() -> None:
    security = _security_config(
        require_auth_default=True,
        api_keys=("secret-key",),
        allowlist=("/public",),
    )
    app = _create_app(security=security)

    with TestClient(app) as client:
        response = client.get("/public")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize(
    "headers",
    (
        {"X-API-Key": "primary"},
        {"Authorization": "ApiKey primary"},
        {"Authorization": "Bearer primary"},
    ),
)
def test_valid_api_key_allows_request(headers: Mapping[str, str]) -> None:
    security = _security_config(require_auth_default=True, api_keys=("primary",))
    app = _create_app(security=security)

    with TestClient(app) as client:
        response = client.get("/protected", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"api_key": "primary"}


def test_missing_api_key_uses_app_state_override(caplog: pytest.LogCaptureFixture) -> None:
    security = _security_config(require_auth_default=False, api_keys=("default",))
    override = _security_config(require_auth_default=True, api_keys=("override",))
    app = _create_app(security=security, override_security=override)

    with TestClient(app) as client, caplog.at_level(logging.INFO):
        response = client.get("/protected")

    assert response.status_code == 401
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "AUTH_REQUIRED",
            "message": "An API key is required to access this resource.",
        },
    }
    record = next(
        record for record in caplog.records if getattr(record, "event", "") == "auth.missing"
    )
    assert record.component == "middleware.auth"
    assert record.status == "error"
    assert record.path == "/protected"
    assert record.method == "GET"


def test_middleware_logs_misconfiguration(caplog: pytest.LogCaptureFixture) -> None:
    security = _security_config(require_auth_default=True, api_keys=())
    app = _create_app(security=security)

    with TestClient(app) as client, caplog.at_level(logging.INFO):
        response = client.get("/protected")

    assert response.status_code == 401
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "AUTH_REQUIRED",
            "message": "An API key is required to access this resource.",
        },
    }
    record = next(
        record for record in caplog.records if getattr(record, "event", "") == "auth.misconfigured"
    )
    assert record.component == "middleware.auth"
    assert record.status == "error"
    assert record.path == "/protected"
    assert record.method == "GET"


@pytest.mark.parametrize(
    "headers",
    (
        {"X-API-Key": "secondary"},
        {"Authorization": "ApiKey secondary"},
        {"Authorization": "Bearer secondary"},
    ),
)
def test_invalid_api_key_returns_forbidden(
    headers: Mapping[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    security = _security_config(require_auth_default=True, api_keys=("primary",))
    app = _create_app(security=security)

    with TestClient(app) as client, caplog.at_level(logging.INFO):
        response = client.get("/protected", headers=headers)

    assert response.status_code == 403
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "AUTH_REQUIRED",
            "message": "The provided API key is not valid.",
        },
    }
    record = next(
        record for record in caplog.records if getattr(record, "event", "") == "auth.invalid"
    )
    assert record.component == "middleware.auth"
    assert record.status == "error"
    assert record.path == "/protected"
    assert record.method == "GET"


@pytest.mark.parametrize(
    "headers",
    (
        {},
        {"Authorization": "Basic secret"},
        {"Authorization": "ApiKey "},
        {"Authorization": "Bearer "},
        {"X-API-Key": ""},
    ),
)
def test_missing_api_key_variants_return_unauthorized(headers: Mapping[str, str]) -> None:
    security = _security_config(require_auth_default=True, api_keys=("primary",))
    app = _create_app(security=security)

    with TestClient(app) as client:
        response = client.get("/protected", headers=headers)

    assert response.status_code == 401
    assert response.json() == {
        "ok": False,
        "error": {
            "code": "AUTH_REQUIRED",
            "message": "An API key is required to access this resource.",
        },
    }
