from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import RateLimitMiddlewareConfig, SecurityConfig
from app.middleware.auth_apikey import ApiKeyAuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware


def _create_security_config() -> SecurityConfig:
    return SecurityConfig(
        profile="prod",
        api_keys=("secret",),
        allowlist=tuple(),
        allowed_origins=("*",),
        _require_auth_default=True,
        _rate_limiting_default=True,
    )


def test_api_key_middleware_enforces_profile_default() -> None:
    security = _create_security_config()
    app = FastAPI()
    app.add_middleware(ApiKeyAuthMiddleware, security=security)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 401


def test_api_key_middleware_respects_profile_override() -> None:
    security = _create_security_config()
    security.require_auth = False
    app = FastAPI()
    app.add_middleware(ApiKeyAuthMiddleware, security=security)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200


def test_rate_limit_middleware_enforces_profile_default() -> None:
    security = _create_security_config()
    rate_config = RateLimitMiddlewareConfig(
        enabled=True,
        bucket_capacity=1,
        refill_per_second=0.0,
    )
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, config=rate_config, security=security)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)

    first = client.get("/health")
    assert first.status_code == 200

    second = client.get("/health")
    assert second.status_code == 429


def test_rate_limit_middleware_respects_profile_override() -> None:
    security = _create_security_config()
    security.rate_limiting_enabled = False
    rate_config = RateLimitMiddlewareConfig(
        enabled=True,
        bucket_capacity=1,
        refill_per_second=0.0,
    )
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, config=rate_config, security=security)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)

    first = client.get("/health")
    assert first.status_code == 200

    second = client.get("/health")
    assert second.status_code == 200
