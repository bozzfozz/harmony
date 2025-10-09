from __future__ import annotations

from typing import Any

from app.api import search as search_module


def test_search_router_emits_api_request_event(monkeypatch, client) -> None:
    captured: list[dict[str, Any]] = []

    def _capture(logger, event: str, /, **fields: Any) -> None:
        payload = {"event": event, **fields}
        captured.append(payload)

    monkeypatch.setattr(search_module, "log_event", _capture)
    monkeypatch.setattr(search_module, "_log_event", _capture)
    monkeypatch.setattr("app.logging_events.log_event", _capture)

    payload = {
        "query": "Track",
        "type": "track",
        "sources": ["soulseek"],
        "limit": 5,
        "offset": 0,
    }

    headers = {"X-Request-ID": "req-test-1"}
    response = client.post("/search", json=payload, headers=headers)

    assert response.status_code == 200

    api_events = [entry for entry in captured if entry["event"] == "api.request"]
    assert api_events, "Expected api.request event"
    event_payload = api_events[-1]
    assert event_payload["component"] == "router.search"
    assert event_payload["status"] in {"ok", "partial"}
    assert event_payload["entity_id"] == "req-test-1"
    assert event_payload["duration_ms"] > 0
    assert event_payload["path"].endswith("/search")
    assert event_payload["method"] == "POST"


def test_search_router_falls_back_to_logging_events(monkeypatch, client) -> None:
    captured: list[dict[str, Any]] = []

    def _capture(logger, event: str, /, **fields: Any) -> None:
        captured.append({"event": event, **fields})

    monkeypatch.setattr(search_module, "log_event", None, raising=False)
    monkeypatch.setattr(search_module, "_log_event", None, raising=False)
    monkeypatch.setattr("app.logging_events.log_event", _capture)

    payload = {
        "query": "Track",
        "type": "track",
        "sources": ["spotify"],
        "limit": 3,
        "offset": 0,
    }

    response = client.post("/search", json=payload)

    assert response.status_code == 200
    events = [entry for entry in captured if entry["event"] == "api.request"]
    assert events, "Expected fallback to app.logging_events.log_event"
