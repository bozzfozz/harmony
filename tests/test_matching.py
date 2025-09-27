from __future__ import annotations

from typing import Generator, List

import pytest

from app import db as app_db
from app.core.matching_engine import MusicMatchingEngine
from app.dependencies import get_db
from app.main import app
from app.models import Match
from tests.simple_client import SimpleTestClient


def _fetch_album_matches() -> List[Match]:
    assert app_db.SessionLocal is not None
    session = app_db.SessionLocal()
    try:
        return session.query(Match).filter(Match.source == "spotify-to-plex-album").all()
    finally:
        session.close()


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


@pytest.mark.skip(reason="Plex matching archived in MVP")
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
            {
                "id": "100",
                "title": "Test Song",
                "artist": "Tester",
                "album": "Album",
                "duration": 200000,
            }
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


@pytest.mark.skip(reason="Plex matching archived in MVP")
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
    assert _fetch_album_matches() == []


@pytest.mark.skip(reason="Plex matching archived in MVP")
def test_matching_api_album_with_persist(client: SimpleTestClient) -> None:
    payload = {
        "spotify_album": {
            "id": "album-1",
            "name": "Test Album",
            "artists": [{"name": "Tester"}],
            "total_tracks": 2,
            "release_date": "2020-05-01",
            "tracks": {
                "items": [
                    {"id": "track-a"},
                    {"id": "track-b"},
                ]
            },
        },
        "candidates": [
            {
                "ratingKey": "201",
                "title": "Test Album",
                "grandparentTitle": "Tester",
                "leafCount": 2,
                "year": 2020,
            }
        ],
    }
    response = client.post(
        "/matching/spotify-to-plex-album",
        json=payload,
        params={"persist": True},
    )
    assert response.status_code == 200
    matches = _fetch_album_matches()
    assert len(matches) == 2
    assert {match.spotify_track_id for match in matches} == {"track-a", "track-b"}
    assert all(match.source == "spotify-to-plex-album" for match in matches)
    assert all(match.target_id == "201" for match in matches)
    assert all(match.context_id == "album-1" for match in matches)


@pytest.mark.skip(reason="Plex matching archived in MVP")
def test_matching_api_album_persist_failure(client: SimpleTestClient) -> None:
    class BrokenSession:
        def add(self, _obj: Match) -> None:
            pass

        def commit(self) -> None:
            raise RuntimeError("database unavailable")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    def broken_get_db() -> Generator[BrokenSession, None, None]:
        session = BrokenSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = broken_get_db
    payload = {
        "spotify_album": {
            "id": "album-2",
            "name": "Another Album",
            "artists": [{"name": "Tester"}],
            "total_tracks": 1,
            "release_date": "2020-05-01",
            "tracks": {"items": [{"id": "track-c"}]},
        },
        "candidates": [
            {
                "ratingKey": "202",
                "title": "Another Album",
                "grandparentTitle": "Tester",
                "leafCount": 1,
                "year": 2020,
            }
        ],
    }
    try:
        response = client.post(
            "/matching/spotify-to-plex-album",
            json=payload,
            params={"persist": True},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 500
    assert _fetch_album_matches() == []
