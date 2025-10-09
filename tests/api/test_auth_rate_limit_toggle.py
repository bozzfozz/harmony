from __future__ import annotations

from typing import Iterator

import pytest
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient

from app.api import middleware as api_middleware
from app.main import app


@pytest.fixture
def client() -> Iterator[SimpleTestClient]:
    with SimpleTestClient(app, include_env_api_key=False) as instance:
        yield instance


@pytest.fixture(autouse=True)
def restore_security_state() -> Iterator[None]:
    security = app.state.security_config
    snapshot = {
        "require_auth": security.require_auth,
        "api_keys": security.api_keys,
        "allowlist": security.allowlist,
        "allowed_origins": security.allowed_origins,
        "rate_limiting_enabled": security.rate_limiting_enabled,
    }
    original_limiter = getattr(app.state, "rate_limiter", None)
    yield
    for field, value in snapshot.items():
        setattr(security, field, value)
    app.state.rate_limiter = original_limiter


def test_authentication_disabled_by_default(client: SimpleTestClient) -> None:
    response = client.get(api_path("health"))
    assert response.status_code in (200, 503)


def test_authentication_enforced_when_enabled(client: SimpleTestClient) -> None:
    security = app.state.security_config
    security.require_auth = True
    security.api_keys = ("test-key",)
    security.allowlist = tuple()  # ensure the tested path is protected

    response = client.get(api_path("health"))
    assert response.status_code == 401

    response = client.get(api_path("health"), headers={"X-API-Key": "test-key"})
    assert response.status_code in (200, 503)


def test_rate_limiting_enabled_blocks_excess_requests(client: SimpleTestClient) -> None:
    security = app.state.security_config
    security.require_auth = False
    security.rate_limiting_enabled = True
    security.allowlist = tuple()
    limiter = api_middleware._RateLimiter(max_requests=1, window_seconds=60)  # type: ignore[attr-defined]
    app.state.rate_limiter = limiter

    first = client.get(api_path("health"))
    assert first.status_code in (200, 503)

    second = client.get(api_path("health"))
    assert second.status_code == 429
