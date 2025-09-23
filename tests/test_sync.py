from __future__ import annotations

from app.workers import PlaylistSyncWorker, ScanWorker


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


def test_search_requires_query(client) -> None:
    response = client.post("/api/search", json={})
    assert response.status_code == 400


def test_search_aggregates_sources(client) -> None:
    response = client.post("/api/search", json={"query": "Test"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "Test"
    assert "spotify" in payload["results"]
    assert "tracks" in payload["results"]["spotify"]
    assert payload["results"].get("soulseek", {}).get("results") == ["Test"]


def test_search_allows_source_filter(client) -> None:
    response = client.post("/api/search", json={"query": "Test", "sources": ["spotify"]})
    assert response.status_code == 200
    payload = response.json()
    assert set(payload["results"].keys()) == {"spotify"}
