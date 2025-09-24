from __future__ import annotations
import importlib

from app.utils.activity import activity_manager


def test_search_records_activity_success(client) -> None:
    response = client.post("/api/search", json={"query": "Test"})
    assert response.status_code == 200

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in entries]
    assert "search_started" in statuses
    assert "search_completed" in statuses

    started = next(entry for entry in entries if entry["status"] == "search_started")
    assert started["details"]["query"] == "Test"
    assert set(started["details"]["sources"]) == {"spotify", "plex", "soulseek"}

    completed = next(entry for entry in entries if entry["status"] == "search_completed")
    matches = completed["details"]["matches"]
    assert set(matches.keys()) == {"spotify", "plex", "soulseek"}
    assert all(isinstance(count, int) for count in matches.values())


def test_search_records_activity_failure(monkeypatch, client) -> None:
    def _raise_plex_error():
        raise RuntimeError("plex offline")

    deps = importlib.import_module("app.dependencies")
    monkeypatch.setattr(deps, "get_plex_client", _raise_plex_error)

    response = client.post("/api/search", json={"query": "Test", "sources": ["plex"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("errors", {}).get("plex") == "Plex client unavailable"

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in entries]
    assert statuses.count("search_started") == 1
    assert "search_completed" in statuses
    assert "search_failed" in statuses

    failed = next(entry for entry in entries if entry["status"] == "search_failed")
    errors = failed["details"]["errors"]
    assert errors
    assert any(item.get("source") == "plex" for item in errors)
