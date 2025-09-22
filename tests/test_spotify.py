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


def test_audio_features_endpoints(client: SimpleTestClient) -> None:
    stub = client.app.state.spotify_stub
    stub.audio_features["track-2"] = {"id": "track-2", "danceability": 0.7}

    single = client.get("/spotify/audio-features/track-1")
    assert single.status_code == 200
    assert single.json()["audio_features"]["id"] == "track-1"

    multiple = client.get("/spotify/audio-features", params={"ids": "track-1,track-2"})
    assert multiple.status_code == 200
    features = multiple.json()["audio_features"]
    assert isinstance(features, list)
    assert {item["id"] for item in features} == {"track-1", "track-2"}


def test_playlist_items_endpoint(client: SimpleTestClient) -> None:
    stub = client.app.state.spotify_stub
    stub.playlist_items["playlist-42"] = {
        "items": [{"track": {"id": "track-1"}}, {"track": {"id": "track-2"}}],
        "total": 2,
    }

    response = client.get("/spotify/playlists/playlist-42/tracks")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_save_and_remove_tracks(client: SimpleTestClient) -> None:
    stub = client.app.state.spotify_stub

    save_response = client.put("/spotify/me/tracks", json={"ids": ["track-1", "track-2"]})
    assert save_response.status_code == 200
    assert stub.saved_track_ids == {"track-1", "track-2"}

    saved = client.get("/spotify/me/tracks")
    assert saved.status_code == 200
    data = saved.json()
    assert data["total"] == 2

    remove_response = client.delete("/spotify/me/tracks", json={"ids": ["track-1"]})
    assert remove_response.status_code == 200
    assert stub.saved_track_ids == {"track-2"}


def test_recommendations_endpoint(client: SimpleTestClient) -> None:
    stub = client.app.state.spotify_stub
    stub.recommendation_payload = {
        "tracks": [{"id": "track-3"}],
        "seeds": [{"type": "track", "id": "track-1"}],
    }

    response = client.get(
        "/spotify/recommendations",
        params={"seed_tracks": "track-1", "limit": 1},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tracks"] == [{"id": "track-3"}]
    assert body["seeds"] == [{"type": "track", "id": "track-1"}]
