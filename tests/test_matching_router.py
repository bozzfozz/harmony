import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.matching_engine import MatchResult
from app.routers import matching_router


def _run(coro):
    return asyncio.run(coro)


def test_match_track_success(monkeypatch):
    match = MatchResult(
        plex_track=SimpleNamespace(title="Song One", artist="Artist A", album="Album X"),
        confidence=0.92,
        match_type="exact",
        is_match=True,
    )

    monkeypatch.setattr(
        matching_router,
        "spotify_client",
        SimpleNamespace(
            is_authenticated=lambda: True,
            get_track_details=lambda _track_id: {
                "id": "1",
                "name": "Song One",
                "artists": ["Artist A"],
                "album": "Album X",
                "raw_data": {
                    "id": "1",
                    "name": "Song One",
                    "artists": [{"name": "Artist A"}],
                    "album": {"id": "alb1", "name": "Album X"},
                    "duration_ms": 210_000,
                },
            },
        ),
    )
    monkeypatch.setattr(
        matching_router,
        "plex_client",
        SimpleNamespace(search_tracks=lambda _query: [SimpleNamespace(title="Song One", artist="Artist A", album="Album X")]),
    )
    monkeypatch.setattr(
        matching_router,
        "engine",
        SimpleNamespace(find_best_match=lambda _spotify, _candidates: match),
    )

    result = _run(matching_router.match_track("track1"))

    assert result.spotify_title == "Song One"
    assert result.plex_title == "Song One"
    assert result.match_type == "exact"
    assert result.is_match is True


def test_match_track_not_authenticated(monkeypatch):
    monkeypatch.setattr(
        matching_router,
        "spotify_client",
        SimpleNamespace(is_authenticated=lambda: False),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run(matching_router.match_track("track1"))

    assert exc_info.value.status_code == 401


def test_match_track_not_found(monkeypatch):
    monkeypatch.setattr(
        matching_router,
        "spotify_client",
        SimpleNamespace(is_authenticated=lambda: True, get_track_details=lambda _track_id: None),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run(matching_router.match_track("track1"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Spotify track not found"


def test_match_track_no_candidates(monkeypatch):
    spotify = SimpleNamespace(
        is_authenticated=lambda: True,
        get_track_details=lambda _track_id: {
            "id": "1",
            "name": "Song One",
            "artists": ["Artist A"],
            "album": "Album X",
            "raw_data": {
                "id": "1",
                "name": "Song One",
                "artists": [{"name": "Artist A"}],
                "album": {"id": "alb1", "name": "Album X"},
                "duration_ms": 210_000,
            },
        },
    )

    monkeypatch.setattr(matching_router, "spotify_client", spotify)
    monkeypatch.setattr(matching_router, "plex_client", SimpleNamespace(search_tracks=lambda _query: []))

    with pytest.raises(HTTPException) as exc_info:
        _run(matching_router.match_track("track1"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "No Plex candidates found"


def test_match_track_generic_error(monkeypatch):
    spotify = SimpleNamespace(
        is_authenticated=lambda: True,
        get_track_details=lambda _track_id: {
            "id": "1",
            "name": "Song One",
            "artists": ["Artist A"],
            "album": "Album X",
            "raw_data": {
                "id": "1",
                "name": "Song One",
                "artists": [{"name": "Artist A"}],
                "album": {"id": "alb1", "name": "Album X"},
                "duration_ms": 210_000,
            },
        },
    )
    monkeypatch.setattr(matching_router, "spotify_client", spotify)
    monkeypatch.setattr(
        matching_router,
        "plex_client",
        SimpleNamespace(search_tracks=lambda _query: [SimpleNamespace(title="Song One", artist="Artist A", album="Album X")]),
    )
    monkeypatch.setattr(
        matching_router,
        "engine",
        SimpleNamespace(find_best_match=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run(matching_router.match_track("track1"))

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "boom"


def test_match_album_success(monkeypatch):
    spotify_album = {
        "id": "alb1",
        "name": "Album X",
        "artists": [{"name": "Artist A"}],
        "release_year": 2020,
    }
    monkeypatch.setattr(
        matching_router,
        "spotify_client",
        SimpleNamespace(is_authenticated=lambda: True, get_album=lambda _album_id: spotify_album),
    )
    monkeypatch.setattr(
        matching_router,
        "plex_client",
        SimpleNamespace(search_albums=lambda _query: [SimpleNamespace(title="Album X", artist="Artist A")]),
    )
    monkeypatch.setattr(
        matching_router,
        "engine",
        SimpleNamespace(find_best_album_match=lambda *_args, **_kwargs: ({"title": "Album X", "artist": "Artist A"}, 0.88)),
    )

    result = _run(matching_router.match_album("album1"))

    assert result.spotify_album == "Album X"
    assert result.plex_album == "Album X"
    assert result.confidence == pytest.approx(0.88)


def test_match_album_not_authenticated(monkeypatch):
    monkeypatch.setattr(
        matching_router,
        "spotify_client",
        SimpleNamespace(is_authenticated=lambda: False),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run(matching_router.match_album("album1"))

    assert exc_info.value.status_code == 401


def test_match_album_not_found(monkeypatch):
    monkeypatch.setattr(
        matching_router,
        "spotify_client",
        SimpleNamespace(is_authenticated=lambda: True, get_album=lambda _album_id: None),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run(matching_router.match_album("album1"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Spotify album not found"


def test_match_album_no_plex_results(monkeypatch):
    spotify_album = {
        "id": "alb1",
        "name": "Album X",
        "artists": [{"name": "Artist A"}],
    }
    monkeypatch.setattr(
        matching_router,
        "spotify_client",
        SimpleNamespace(is_authenticated=lambda: True, get_album=lambda _album_id: spotify_album),
    )
    monkeypatch.setattr(matching_router, "plex_client", SimpleNamespace(search_albums=lambda _query: []))

    with pytest.raises(HTTPException) as exc_info:
        _run(matching_router.match_album("album1"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "No Plex albums found"


def test_match_album_no_confident_match(monkeypatch):
    spotify_album = {
        "id": "alb1",
        "name": "Album X",
        "artists": [{"name": "Artist A"}],
    }
    monkeypatch.setattr(
        matching_router,
        "spotify_client",
        SimpleNamespace(is_authenticated=lambda: True, get_album=lambda _album_id: spotify_album),
    )
    monkeypatch.setattr(
        matching_router,
        "plex_client",
        SimpleNamespace(search_albums=lambda _query: [SimpleNamespace(title="Album X", artist="Artist A")]),
    )
    monkeypatch.setattr(
        matching_router,
        "engine",
        SimpleNamespace(find_best_album_match=lambda *_args, **_kwargs: (None, 0.3)),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run(matching_router.match_album("album1"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "No confident match found"


def test_match_album_generic_error(monkeypatch):
    spotify_album = {
        "id": "alb1",
        "name": "Album X",
        "artists": [{"name": "Artist A"}],
    }
    monkeypatch.setattr(
        matching_router,
        "spotify_client",
        SimpleNamespace(is_authenticated=lambda: True, get_album=lambda _album_id: spotify_album),
    )
    monkeypatch.setattr(
        matching_router,
        "plex_client",
        SimpleNamespace(search_albums=lambda _query: [SimpleNamespace(title="Album X", artist="Artist A")]),
    )
    monkeypatch.setattr(
        matching_router,
        "engine",
        SimpleNamespace(find_best_album_match=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("kaboom"))),
    )

    with pytest.raises(HTTPException) as exc_info:
        _run(matching_router.match_album("album1"))

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "kaboom"
