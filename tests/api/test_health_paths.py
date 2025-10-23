from __future__ import annotations

from collections.abc import Iterable

from fastapi.testclient import TestClient
import pytest

from app.main import app


@pytest.fixture(scope="module")
def client() -> Iterable[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "method,path,allowed_statuses",
    [
        ("GET", "/live", {200}),
        ("GET", "/api/health/live", {200}),
        ("GET", "/api/health/ready", {200, 503}),
        ("GET", "/api/v1/status", {200}),
        ("GET", "/api/v1/health", {200}),
        ("GET", "/api/v1/ready", {200, 503}),
        ("GET", "/api/v1/metrics", {200}),
    ],
)
def test_documented_health_routes_do_not_404(
    client: TestClient, method: str, path: str, allowed_statuses: set[int]
) -> None:
    response = client.request(method, path)

    assert response.status_code in allowed_statuses, (
        f"{method} {path} returned {response.status_code}, "
        f"expected one of {sorted(allowed_statuses)}"
    )
