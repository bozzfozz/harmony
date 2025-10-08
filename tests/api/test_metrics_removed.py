from __future__ import annotations

from app.main import app
from tests.simple_client import SimpleTestClient


def test_metrics_endpoint_is_not_exposed() -> None:
    with SimpleTestClient(app) as client:
        response = client.get("/metrics", use_raw_path=True)
    assert response.status_code == 404
