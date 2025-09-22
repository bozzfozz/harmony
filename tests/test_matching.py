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


def test_album_matching_engine() -> None:
    engine = MusicMatchingEngine()
    spotify_album = {
        "id": "album-1",
        "name": "Test Album",
        "artists": [{"name": "Tester"}],
        "total_tracks": 10,
        "release_date": "2020-05-01",
    }
    plex_albums = [
        {
            "ratingKey": "201",
            "title": "Test Album",
            "grandparentTitle": "Tester",
            "leafCount": 10,
            "year": 2020,
        },
        {
            "ratingKey": "202",
            "title": "Other Album",
            "grandparentTitle": "Tester",
            "leafCount": 8,
            "year": 2018,
        },
    ]
    match, score = engine.find_best_album_match(spotify_album, plex_albums)
    assert match["ratingKey"] == "201"
    assert score > 0.8


def test_matching_api_album(client: SimpleTestClient) -> None:
    payload = {
        "spotify_album": {
            "id": "album-1",
            "name": "Test Album",
            "artists": [{"name": "Tester"}],
            "total_tracks": 10,
            "release_date": "2020-05-01",
        },
        "candidates": [
            {
                "ratingKey": "201",
                "title": "Test Album",
                "grandparentTitle": "Tester",
                "leafCount": 10,
                "year": 2020,
            },
            {
                "ratingKey": "202",
                "title": "Other Album",
                "grandparentTitle": "Tester",
                "leafCount": 8,
                "year": 2018,
            },
        ],
    }
    response = client.post("/matching/spotify-to-plex-album", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["best_match"]["ratingKey"] == "201"
    assert data["confidence"] > 0.8
