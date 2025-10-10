from __future__ import annotations

from fastapi.testclient import TestClient

from fastapi import FastAPI
from fastapi.testclient import TestClient

import pytest

from app import dependencies as deps
from app.api import health as health_api

pytestmark = pytest.mark.no_database


@pytest.fixture
def health_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    deps.get_app_config.cache_clear()
    monkeypatch.setenv("HEALTH_READY_REQUIRE_DB", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    test_app = FastAPI()
    test_app.include_router(health_api.router)
    with TestClient(test_app) as client:
        yield client
    deps.get_app_config.cache_clear()


def test_ready_endpoint_verbose_success(health_client: TestClient) -> None:
    response = health_client.get("/api/health/ready", params={"verbose": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    checks = payload["checks"]
    assert checks["env"]["status"] == "ok"
    assert checks["soulseekd"]["reachable"] is True


def test_ready_endpoint_reports_missing_env(
    health_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    response = health_client.get("/api/health/ready", params={"verbose": 1})
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "fail"
    assert "SPOTIFY_CLIENT_SECRET" in payload["checks"]["env"]["missing"]


def test_ready_endpoint_reports_unwritable_path(
    health_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    bad_path = tmp_path / "downloads"
    bad_path.write_text("not-a-directory")
    monkeypatch.setenv("DOWNLOADS_DIR", str(bad_path))
    response = health_client.get("/api/health/ready", params={"verbose": 1})
    assert response.status_code == 503
    payload = response.json()
    downloads = payload["checks"]["paths"]["downloads"]
    assert downloads["exists"] is True
    assert downloads["is_dir"] is False
