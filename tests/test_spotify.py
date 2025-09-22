from __future__ import annotations

from tests.simple_client import SimpleTestClient

from app.db import session_scope
from app.models import Playlist
from app.workers.playlist_sync_worker import PlaylistSyncWorker


def test_playlist_sync_worker_persists_playlists(client: SimpleTestClient) -> None:
    stub = client.app.state.spotify_stub
    stub.playlists = [
        {"id": "playlist-1", "name": "Focus", "tracks": {"total": 12}},
        {"id": "playlist-2", "name": "Relax", "track_count": 8},
    ]

    worker = PlaylistSyncWorker(stub, interval_seconds=0.1)
    client._loop.run_until_complete(worker.sync_once())

    with session_scope() as session:
        records = session.query(Playlist).all()
        assert len(records) == 2

    response = client.get("/spotify/playlists")
    assert response.status_code == 200
    playlists = response.json()["playlists"]
    assert {entry["id"] for entry in playlists} == {"playlist-1", "playlist-2"}
    first = next(item for item in playlists if item["id"] == "playlist-1")
    assert first["track_count"] == 12

    stub.playlists = [
        {"id": "playlist-1", "name": "Focus Updated", "tracks": {"total": 15}},
    ]
    client._loop.run_until_complete(worker.sync_once())

    response = client.get("/spotify/playlists")
    assert response.status_code == 200
    playlists = response.json()["playlists"]
    assert len(playlists) == 2
    updated = next(item for item in playlists if item["id"] == "playlist-1")
    assert updated["name"] == "Focus Updated"
    assert updated["track_count"] == 15
    assert playlists[0]["id"] == "playlist-1"
