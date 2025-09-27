from __future__ import annotations

import pytest

from app.utils.activity import activity_manager

try:
    from app.workers import PlaylistSyncWorker, ScanWorker
except ImportError:  # pragma: no cover - archived integration
    pytest.skip("Plex sync worker archived in MVP", allow_module_level=True)


def test_sync_endpoint_triggers_workers(monkeypatch, client) -> None:
    calls: dict[str, int] = {"playlist": 0, "scan": 0}

    async def fake_sync_once(self) -> None:  # type: ignore[override]
        calls["playlist"] += 1

    async def fake_run_once(self) -> None:  # type: ignore[override]
        calls["scan"] += 1

    monkeypatch.setattr(PlaylistSyncWorker, "sync_once", fake_sync_once, raising=False)
    monkeypatch.setattr(ScanWorker, "run_once", fake_run_once, raising=False)

    response = client.post("/api/sync")
    assert response.status_code == 202
    body = response.json()
    assert body["results"]["playlists"] == "completed"
    assert body["results"]["library_scan"] == "completed"
    assert calls == {"playlist": 1, "scan": 1}

    entries = activity_manager.list()
    manual_started = next(
        (
            entry
            for entry in entries
            if entry["status"] == "sync_started"
            and entry.get("details", {}).get("mode") == "manual"
        ),
        None,
    )
    assert manual_started is not None
    manual_completed = next(
        (
            entry
            for entry in entries
            if entry["status"] == "sync_completed"
            and entry.get("details", {}).get("mode") == "manual"
        ),
        None,
    )
    assert manual_completed is not None
    counters = manual_completed["details"]["counters"]
    assert counters == {"tracks_synced": 0, "tracks_skipped": 0, "errors": 0}


def test_search_requires_query(client) -> None:
    response = client.post("/api/search", json={})
    assert response.status_code == 422


def test_search_aggregates_sources(client) -> None:
    response = client.post("/api/search", json={"query": "Test"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["offset"] == 0
    assert payload["total"] >= 1
    sources = {item.get("source") for item in payload["items"]}
    assert {"spotify", "plex", "soulseek"}.issubset(sources)


def test_search_allows_source_filter(client) -> None:
    response = client.post("/api/search", json={"query": "Test", "sources": ["spotify"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]
    assert {item.get("source") for item in payload["items"]} == {"spotify"}
