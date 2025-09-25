from __future__ import annotations

from typing import Any, Dict


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
            ],
        }
    ]


def test_search_tracks_with_filters(client) -> None:
    _prepare_soulseek_results(client)
    plex_stub = client.app.state.plex_stub
    plex_stub.library_items[("1", "10")] = {
        "MediaContainer": {
            "Metadata": [
                {
                    "ratingKey": "plex-1",
                    "title": "Great Track",
                    "parentTitle": "Test Album",
                    "grandparentTitle": "Plex Artist",
                    "year": 1969,
                    "Media": [{"bitrate": 1000, "audioCodec": "flac"}],
                    "Genre": [{"tag": "rock"}],
                },
                {
                    "ratingKey": "plex-2",
                    "title": "Old Song",
                    "parentTitle": "Other Album",
                    "grandparentTitle": "Plex Artist",
                    "year": 1940,
                    "Media": [{"bitrate": 192, "audioCodec": "mp3"}],
                    "Genre": [{"tag": "jazz"}],
                },
            ]
        }
    }

    payload: Dict[str, Any] = {
        "query": "Track",
        "filters": {
            "types": ["track"],
            "year_range": [1960, 1980],
            "min_bitrate": 500,
        },
        "sort": {"by": "relevance", "order": "desc"},
        "pagination": {"page": 1, "size": 10},
    }

    response = client.post("/search", json=payload)
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert body["total"] >= 2
    assert {item["type"] for item in items} == {"track"}
    sources = {item["source"] for item in items}
    assert sources <= {"plex", "soulseek"}
    for item in items:
        assert item["year"] == 1969
        assert item.get("bitrate") is None or item["bitrate"] >= 500


def test_search_prefers_flac_over_mp3(client) -> None:
    _prepare_soulseek_results(client)
    payload = {
        "query": "Track",
        "sources": ["soulseek"],
        "filters": {"types": ["track"], "preferred_formats": ["flac"]},
        "pagination": {"page": 1, "size": 5},
    }

    response = client.post("/search", json=payload)
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    formats = [item.get("format") for item in items]
    assert "flac" in formats and "mp3" in formats
    assert items[0]["format"] == "flac"


def test_pagination_and_total(client) -> None:
    spotify_stub = client.app.state.spotify_stub
    base_track = spotify_stub.tracks["track-1"]
    for index in range(40):
        track_id = f"track-extra-{index}"
        spotify_stub.tracks[track_id] = {
            **base_track,
            "id": track_id,
            "name": f"Extra Track {index}",
        }

    payload = {
        "query": "Extra",
        "sources": ["spotify"],
        "filters": {"types": ["track"]},
        "pagination": {"page": 2, "size": 10},
        "sort": {"by": "relevance", "order": "desc"},
    }

    response = client.post("/search", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["size"] == 10
    assert body["total"] >= 40
    assert len(body["items"]) == 10


def test_soft_fail_source_down(monkeypatch, client) -> None:
    plex_stub = client.app.state.plex_stub

    async def _failing_search(*args, **kwargs):  # type: ignore[override]
        raise RuntimeError("plex offline")

    monkeypatch.setattr(plex_stub, "search_music", _failing_search)

    response = client.post("/search", json={"query": "Test"})
    assert response.status_code == 200
    body = response.json()
    assert body["errors"]["plex"] == "Plex source unavailable"
    sources = {item["source"] for item in body["items"]}
    assert "spotify" in sources or "soulseek" in sources
    assert "plex" not in sources


def test_explicit_filter(client) -> None:
    spotify_stub = client.app.state.spotify_stub
    spotify_stub.tracks["track-explicit"] = {
        "id": "track-explicit",
        "name": "Explicit Hit",
        "artists": [{"name": "Tester"}],
        "album": {
            "name": "Explicit Album",
            "release_date": "2020-01-01",
            "artists": [{"name": "Tester"}],
        },
        "duration_ms": 210000,
        "explicit": True,
    }
    spotify_stub.tracks["track-clean"] = {
        "id": "track-clean",
        "name": "Clean Song",
        "artists": [{"name": "Tester"}],
        "album": {
            "name": "Clean Album",
            "release_date": "2020-01-01",
            "artists": [{"name": "Tester"}],
        },
        "duration_ms": 200000,
        "explicit": False,
    }

    payload = {
        "query": "Song",
        "sources": ["spotify"],
        "filters": {"types": ["track"], "explicit": False},
        "pagination": {"page": 1, "size": 20},
        "sort": {"by": "relevance", "order": "desc"},
    }

    response = client.post("/search", json=payload)
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert items
    assert all(item["source"] == "spotify" for item in items)
    assert all(item.get("explicit") is False for item in items)
