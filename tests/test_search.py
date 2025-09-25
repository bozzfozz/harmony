from __future__ import annotations
import importlib

from app.utils.activity import activity_manager


def test_search_records_activity_success(client) -> None:
    response = client.post("/api/search", json={"query": "Test"})
    assert response.status_code == 200
    payload = response.json()
    results = payload["results"]
    assert {item["source"] for item in results} == {"spotify", "plex", "soulseek"}
    for item in results:
        assert {"id", "source", "type", "artist", "album", "title", "year", "quality"}.issubset(item.keys())

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in entries]
    assert "search_started" in statuses
    assert "search_completed" in statuses

    started = next(entry for entry in entries if entry["status"] == "search_started")
    assert started["details"]["query"] == "Test"
    assert set(started["details"]["sources"]) == {"spotify", "plex", "soulseek"}
    assert "filters" not in started["details"]

    completed = next(entry for entry in entries if entry["status"] == "search_completed")
    matches = completed["details"]["matches"]
    assert matches == {"plex": 1, "soulseek": 1, "spotify": 3}


def test_search_applies_quality_filter(client) -> None:
    response = client.post(
        "/api/search",
        json={"query": "Test", "quality": "FLAC"},
    )
    assert response.status_code == 200
    payload = response.json()
    results = payload["results"]
    assert results
    assert all("FLAC" in (item.get("quality") or "") for item in results)
    assert "spotify" not in {item["source"] for item in results}
    assert payload["filters"]["quality"] == "FLAC"

    entries = activity_manager.list()
    started = next(entry for entry in entries if entry["status"] == "search_started")
    assert started["details"]["filters"]["quality"] == "FLAC"


def test_search_applies_year_and_genre_filters(client) -> None:
    response = client.post(
        "/api/search",
        json={"query": "Test", "year": 1969, "genre": "rock"},
    )
    assert response.status_code == 200
    payload = response.json()
    results = payload["results"]
    assert results
    assert all(item.get("year") in {1969, None} for item in results)

    spotify_stub = client.app.state.spotify_stub
    plex_stub = client.app.state.plex_stub
    assert spotify_stub.last_requests["tracks"]["genre"] == "rock"
    assert spotify_stub.last_requests["tracks"]["year"] == 1969
    assert plex_stub.last_library_params[("1", "10")]["genre"] == "rock"
    assert plex_stub.last_library_params[("1", "10")]["year"] == 1969


def test_search_records_activity_failure(monkeypatch, client) -> None:
    def _raise_plex_error():
        raise RuntimeError("plex offline")

    deps = importlib.import_module("app.dependencies")
    monkeypatch.setattr(deps, "get_plex_client", _raise_plex_error)

    response = client.post("/api/search", json={"query": "Test", "sources": ["plex"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("errors", {}).get("plex") == "Plex client unavailable"
    assert payload["results"] == []

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in entries]
    assert statuses.count("search_started") == 1
    assert "search_completed" in statuses
    assert "search_failed" in statuses

    failed = next(entry for entry in entries if entry["status"] == "search_failed")
    errors = failed["details"]["errors"]
    assert errors
    assert any(item.get("source") == "plex" for item in errors)
