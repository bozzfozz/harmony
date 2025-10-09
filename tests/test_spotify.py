from __future__ import annotations

from app.db import session_scope
from app.models import Playlist
from tests.simple_client import SimpleTestClient


def test_playlist_sync_worker_persists_playlists(client: SimpleTestClient) -> None:
    stub = client.app.state.spotify_stub
    stub.playlists = [
        {"id": "playlist-1", "name": "Focus", "tracks": {"total": 12}},
        {"id": "playlist-2", "name": "Relax", "track_count": 8},
    ]

    worker = client.app.state.playlist_worker
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
    etag_initial = response.headers.get("etag")

    cached_response = client.get("/spotify/playlists")
    assert cached_response.status_code == 200
    cached_header_names = {key.lower() for key in cached_response.headers}
    assert "age" in cached_header_names

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
    etag_updated = response.headers.get("etag")
    assert etag_updated is not None and etag_initial is not None
    assert etag_updated != etag_initial


def test_playlist_cache_invalidation(client: SimpleTestClient) -> None:
    stub = client.app.state.spotify_stub
    stub.playlists = [
        {"id": "playlist-1", "name": "Morning", "tracks": {"total": 10}},
        {"id": "playlist-2", "name": "Chill", "track_count": 4},
    ]
    stub.tracks["track-2"] = {
        "id": "track-2",
        "name": "Morning Anthem",
        "artists": [{"name": "Dawn Ensemble"}],
        "album": {
            "id": "album-2",
            "name": "Sunrise",
            "artists": [{"name": "Dawn Ensemble"}],
        },
        "duration_ms": 210_000,
    }
    stub.playlist_items["playlist-1"] = {
        "items": [{"track": dict(stub.tracks["track-1"])}],
        "total": 1,
    }

    worker = client.app.state.playlist_worker
    client._loop.run_until_complete(worker.sync_once())

    initial = client.get("/spotify/playlists")
    assert initial.status_code == 200
    initial_payload = initial.json()["playlists"]
    assert {item["id"] for item in initial_payload} == {"playlist-1", "playlist-2"}
    initial_etag = initial.headers.get("etag")
    assert initial_etag is not None

    cached = client.get("/spotify/playlists")
    assert cached.status_code == 200
    assert cached.headers.get("etag") == initial_etag
    assert "age" in {key.lower() for key in cached.headers}

    detail_initial = client.get("/spotify/playlists/playlist-1/tracks")
    assert detail_initial.status_code == 200
    detail_payload = detail_initial.json()
    assert detail_payload["total"] == 1
    first_track = detail_payload["items"][0]
    assert first_track["id"] == "track-1"
    detail_initial_etag = detail_initial.headers.get("etag")
    assert detail_initial_etag is not None

    detail_cached = client.get("/spotify/playlists/playlist-1/tracks")
    assert detail_cached.status_code == 200
    assert detail_cached.headers.get("etag") == detail_initial_etag
    assert "age" in {key.lower() for key in detail_cached.headers}

    stub.playlists = [
        {"id": "playlist-1", "name": "Morning Updated", "tracks": {"total": 25}},
        {"id": "playlist-2", "name": "Chill", "track_count": 4},
    ]
    stub.playlist_items["playlist-1"] = {
        "items": [{"track": dict(stub.tracks["track-2"])}],
        "total": 1,
    }
    client._loop.run_until_complete(worker.sync_once())

    refreshed = client.get("/spotify/playlists")
    assert refreshed.status_code == 200
    refreshed_data = refreshed.json()["playlists"]
    updated = next(item for item in refreshed_data if item["id"] == "playlist-1")
    assert updated["name"] == "Morning Updated"
    assert updated["track_count"] == 25
    refreshed_etag = refreshed.headers.get("etag")
    assert refreshed_etag is not None
    assert refreshed_etag != initial_etag
    age_header = refreshed.headers.get("Age")
    if age_header is not None:
        assert int(age_header) <= 1

    cached_after = client.get("/spotify/playlists")
    assert cached_after.status_code == 200
    assert cached_after.headers.get("etag") == refreshed_etag
    assert "age" in {key.lower() for key in cached_after.headers}

    detail_refreshed = client.get("/spotify/playlists/playlist-1/tracks")
    assert detail_refreshed.status_code == 200
    detail_refreshed_payload = detail_refreshed.json()
    assert detail_refreshed_payload["total"] == 1
    updated_track = detail_refreshed_payload["items"][0]
    assert updated_track["id"] == "track-2"
    detail_refreshed_etag = detail_refreshed.headers.get("etag")
    assert detail_refreshed_etag is not None
    assert detail_refreshed_etag != detail_initial_etag
    detail_age_header = detail_refreshed.headers.get("Age")
    if detail_age_header is not None:
        assert int(detail_age_header) <= 1

    detail_cached_after = client.get("/spotify/playlists/playlist-1/tracks")
    assert detail_cached_after.status_code == 200
    assert detail_cached_after.headers.get("etag") == detail_refreshed_etag
    assert "age" in {key.lower() for key in detail_cached_after.headers}


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

    save_response = client.put(
        "/spotify/me/tracks", json={"ids": ["track-1", "track-2"]}
    )
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
