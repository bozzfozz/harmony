from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_logging_api_request_emits_event_with_duration(monkeypatch) -> None:
    captured: list[tuple[str, dict]] = []

    def _capture(logger, event_name: str, /, **fields):
        captured.append((event_name, fields))

    monkeypatch.setattr("app.middleware.request_logging.log_event", _capture)

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert captured, "expected api.request event"

    event_name, payload = captured[-1]
    assert event_name == "api.request"
    assert payload["component"] == "api"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/v1/health"
    assert payload["status"] == "ok"
    assert payload["status_code"] == 200
    assert isinstance(payload["duration_ms"], float)
    assert payload["duration_ms"] >= 0.0
    assert payload["entity_id"]


def test_health_endpoint_returns_status_snapshot() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["status"]
    assert body["data"]["version"] == app.version


def test_ready_endpoint_reports_dependencies() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "deps" in body["data"]
