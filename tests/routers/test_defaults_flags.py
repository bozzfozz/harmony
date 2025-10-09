"""Regression tests for default feature flag behaviour."""

from __future__ import annotations

from typing import Iterator

import pytest
from tests.simple_client import SimpleTestClient

from app import dependencies as deps
from app.main import app


@pytest.fixture(autouse=True)
def _reset_flags(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure feature flag environment defaults for each test."""

    for key in (
        "FEATURE_REQUIRE_AUTH",
        "FEATURE_RATE_LIMITING",
    ):
        monkeypatch.delenv(key, raising=False)

    deps.get_app_config.cache_clear()
    app.openapi_schema = None
    yield
    deps.get_app_config.cache_clear()
    app.openapi_schema = None


def test_default_auth_disabled_allows_requests_without_key() -> None:
    with SimpleTestClient(app, include_env_api_key=False) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_default_rate_limit_does_not_return_429() -> None:
    statuses: list[int] = []
    with SimpleTestClient(app, include_env_api_key=False) as client:
        for _ in range(5):
            statuses.append(client.get("/").status_code)

    assert all(status == 200 for status in statuses)


def test_metrics_endpoint_removed() -> None:
    with SimpleTestClient(app, include_env_api_key=False) as client:
        response = client.get("/metrics", use_raw_path=True)

    assert response.status_code == 404


def test_openapi_marks_security_as_optional() -> None:
    schema = app.openapi()

    assert schema.get("security") == []
    paths = schema.get("paths", {})
    assert "/metrics" not in paths
