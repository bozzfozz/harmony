from __future__ import annotations

from app.core.matching_engine import MusicMatchingEngine
from tests.simple_client import SimpleTestClient


def test_match_confidence() -> None:
    engine = MusicMatchingEngine()
    spotify_track = {
        "id": "track-1",
        "name": "Test Song",
        "artists": [{"name": "Tester"}],
        "album": {"name": "Album"},
        "duration_ms": 200000,
    }
    plex_track = {
        "id": "100",
        "title": "Test Song",
        "artist": "Tester",
        "album": "Album",
        "duration": 200000,
    }
    score = engine.calculate_match_confidence(spotify_track, plex_track)
    assert score > 0.8


def test_matching_api_plex(client: SimpleTestClient) -> None:
    payload = {
        "spotify_track": {
            "id": "track-1",
            "name": "Test Song",
            "artists": [{"name": "Tester"}],
            "album": {"name": "Album"},
            "duration_ms": 200000,
        },
        "candidates": [
            {"id": "100", "title": "Test Song", "artist": "Tester", "album": "Album", "duration": 200000}
        ],
    }
    response = client.post("/matching/spotify-to-plex", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["best_match"]["id"] == "100"
    assert data["confidence"] > 0.5


def test_matching_api_soulseek(client: SimpleTestClient) -> None:
    payload = {
        "spotify_track": {
            "id": "track-1",
            "name": "Test Song",
            "artists": [{"name": "Tester"}],
            "album": {"name": "Album"},
        },
        "candidates": [
            {"filename": "Tester - Test Song.mp3", "username": "Tester", "bitrate": 320}
        ],
    }
    response = client.post("/matching/spotify-to-soulseek", json=payload)
    assert response.status_code == 200
    assert response.json()["confidence"] > 0.5
