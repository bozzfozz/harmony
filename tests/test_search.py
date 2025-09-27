from __future__ import annotations

from typing import Any, Dict

import pytest

from app.core.matching_engine import MusicMatchingEngine


def _prepare_soulseek_results(client) -> None:
    soulseek_stub = client.app.state.soulseek_stub
    soulseek_stub.search_results = [
        {
            "username": "user-1",
            "files": [
                {
                    "id": "soulseek-flac",
                    "filename": "Great Track.flac",
                    "title": "Great Track",
                    "artist": "Soulseek Artist",
                    "album": "Soulseek Album",
                    "bitrate": 1000,
                    "format": "flac",
                    "year": 1969,
                    "genre": "rock",
                },
                {
                    "id": "soulseek-mp3",
                    "filename": "Other Track.mp3",
                    "title": "Other Track",
                    "artist": "Soulseek Artist",
                    "album": "Soulseek Album",
                    "bitrate": 320,
                    "format": "mp3",
                    "year": 1969,
                    "genre": "rock",
                },
                {
                    "id": "soulseek-low",
                    "filename": "Low Quality.mp3",
                    "title": "Low Quality",
                    "artist": "Soulseek Artist",
                    "album": "Soulseek Album",
                    "bitrate": 192,
                    "format": "mp3",
                    "year": 1968,
                    "genre": "rock",
                },
            ],
        }
    ]


def test_search_filters_by_year_range(client) -> None:
    _prepare_soulseek_results(client)

    payload: Dict[str, Any] = {
        "query": "Track",
        "type": "track",
        "sources": ["soulseek"],
        "year_from": 1960,
        "year_to": 1980,
        "limit": 10,
        "offset": 0,
    }

    response = client.post("/search", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["total"] >= 1
    for item in body["items"]:
        assert 1960 <= item["year"] <= 1980
        assert item["source"] == "soulseek"


def test_search_filters_by_genre(client) -> None:
    _prepare_soulseek_results(client)
    spotify_stub = client.app.state.spotify_stub
    spotify_stub.tracks["track-genre"] = {
        "id": "track-genre",
        "name": "Genre Match",
        "artists": [{"name": "Tester"}],
        "album": {
            "name": "Genre Album",
            "release_date": "1970-01-01",
            "artists": [{"name": "Tester"}],
        },
        "genre": "Rock",
    }

    payload = {
        "query": "Genre",
        "type": "mixed",
        "sources": ["spotify", "soulseek"],
        "genre": "rock",
        "limit": 10,
        "offset": 0,
    }

    response = client.post("/search", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["total"] >= 1
    assert body["items"], "Expected at least one genre-filtered result"
    for item in body["items"]:
        genres = [genre.lower() for genre in item.get("genres", [])]
        assert any("rock" in genre for genre in genres)


def test_search_respects_min_bitrate_and_format_priority(client) -> None:
    _prepare_soulseek_results(client)
    payload = {
        "query": "Track",
        "type": "track",
        "sources": ["soulseek"],
        "min_bitrate": 320,
        "format_priority": ["FLAC", "MP3"],
        "limit": 5,
        "offset": 0,
    }

    response = client.post("/search", json=payload)
    assert response.status_code == 200
    body = response.json()
    formats = [item.get("format") for item in body["items"]]
    assert formats[0] == "FLAC"
    assert all(item.get("bitrate", 0) >= 320 for item in body["items"])


def test_search_ranking_boosts_format_and_type(monkeypatch: pytest.MonkeyPatch, client) -> None:
    _prepare_soulseek_results(client)

    def _constant_score(self, query: str, candidate: Dict[str, Any]) -> float:  # noqa: D401
        return 0.4

    monkeypatch.setattr(MusicMatchingEngine, "compute_relevance_score", _constant_score)

    payload = {
        "query": "Track",
        "type": "track",
        "sources": ["spotify", "soulseek"],
        "format_priority": ["FLAC", "MP3"],
        "limit": 10,
        "offset": 0,
    }

    response = client.post("/search", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["items"], "Expected ranked results"
    first, second = body["items"][0], body["items"][1]
    assert first["source"] == "soulseek"
    assert first["score"] >= 0.73
    assert first["score"] > second["score"]


def test_search_validation_errors(client) -> None:
    payload = {
        "query": "Test",
        "year_from": 2030,
        "year_to": 2010,
    }
    response = client.post("/search", json=payload)
    assert response.status_code == 422
