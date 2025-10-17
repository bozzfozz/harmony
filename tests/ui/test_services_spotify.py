"""Unit tests for :mod:`app.ui.services.spotify`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Mapping
from unittest.mock import Mock

from starlette.requests import Request

from app.ui.services.spotify import (
    SpotifyAccountSummary,
    SpotifyArtistRow,
    SpotifySavedTrackRow,
    SpotifyUiService,
)


class _StubOAuthService:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self._payload = payload

    def health(self) -> Mapping[str, object]:
        return self._payload


def _make_request() -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/ui/spotify",
        "headers": [],
    }
    return Request(scope)


def test_oauth_health_hides_redirect_when_manual_disabled() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    oauth = _StubOAuthService(
        {
            "manual_enabled": False,
            "redirect_uri": "https://example/callback",
            "public_host_hint": "https://public.example",
            "active_transactions": 2,
            "ttl_seconds": 120,
        }
    )
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=Mock(),
        oauth_service=oauth,
        db_session=Mock(),
    )

    health = service.oauth_health()

    assert health.manual_enabled is False
    assert health.redirect_uri is None
    assert health.public_host_hint == "https://public.example"
    assert health.active_transactions == 2
    assert health.ttl_seconds == 120


def test_oauth_health_keeps_redirect_when_manual_enabled() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    oauth = _StubOAuthService(
        {
            "manual_enabled": True,
            "redirect_uri": "https://example/callback",
            "public_host_hint": None,
            "active_transactions": None,
            "ttl_seconds": None,
        }
    )
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=Mock(),
        oauth_service=oauth,
        db_session=Mock(),
    )

    health = service.oauth_health()

    assert health.manual_enabled is True
    assert health.redirect_uri == "https://example/callback"
    assert health.public_host_hint is None
    assert health.active_transactions == 0
    assert health.ttl_seconds == 0


def test_list_followed_artists_normalizes_payload() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_followed_artists.return_value = [
        {
            "id": "artist-1",
            "name": "Artist One",
            "followers": {"total": 43210},
            "popularity": 92,
            "genres": ["rock", " pop ", ""],
        },
        {
            "id": "",
            "name": "Missing",
        },
    ]
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    rows = service.list_followed_artists()

    assert rows == (
        SpotifyArtistRow(
            identifier="artist-1",
            name="Artist One",
            followers=43210,
            popularity=92,
            genres=("rock", "pop"),
        ),
    )
    spotify_service.get_followed_artists.assert_called_once_with()


def test_account_returns_summary_with_defaults() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_current_user.return_value = {
        "display_name": "Example User",
        "id": "example-id",
        "product": "premium",
        "followers": {"total": "2500"},
        "country": "gb",
    }
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    summary = service.account()

    assert summary == SpotifyAccountSummary(
        display_name="Example User",
        product="Premium",
        followers=2500,
        country="GB",
    )
    spotify_service.get_current_user.assert_called_once_with()


def test_account_handles_missing_profile() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_current_user.return_value = {
        "display_name": " ",
        "id": "user-123",
        "followers": None,
        "country": None,
    }
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    summary = service.account()

    assert summary == SpotifyAccountSummary(
        display_name="user-123",
        product=None,
        followers=0,
        country=None,
    )

    spotify_service.get_current_user.assert_called_once_with()


def test_list_saved_tracks_normalizes_payload() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_saved_tracks.return_value = {
        "items": [
            {
                "added_at": "2023-09-01T10:00:00Z",
                "track": {
                    "id": "track-1",
                    "name": "Track One",
                    "artists": [
                        {"name": "Artist One"},
                        {"name": " Artist Two "},
                    ],
                    "album": {"name": " Album Name "},
                },
            },
            {
                "added_at": None,
                "track": {
                    "id": "track-2",
                    "name": "Track Two",
                    "artists": ["Solo"],
                    "album": {},
                },
            },
        ],
        "total": 2,
    }
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    rows, total = service.list_saved_tracks(limit=1, offset=0)

    assert total == 2
    assert rows == (
        SpotifySavedTrackRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist One", "Artist Two"),
            album="Album Name",
            added_at=rows[0].added_at,
        ),
    )
    assert rows[0].added_at.isoformat() == "2023-09-01T10:00:00+00:00"
    spotify_service.get_saved_tracks.assert_called_once_with(limit=1, offset=0)


def test_list_saved_tracks_applies_offset() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_saved_tracks.return_value = {
        "items": [
            {
                "added_at": "2023-09-02T10:00:00Z",
                "track": {"id": "track-2", "name": "Track Two", "artists": [], "album": {}},
            },
        ],
        "total": 2,
    }
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    rows, total = service.list_saved_tracks(limit=1, offset=1)

    assert total == 2
    assert len(rows) == 1
    assert rows[0].identifier == "track-2"
    spotify_service.get_saved_tracks.assert_called_once_with(limit=1, offset=1)


def test_save_tracks_filters_and_returns_count() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    affected = service.save_tracks([" track-1 ", "track-1", "track-2", " "])

    assert affected == 2
    spotify_service.save_tracks.assert_called_once_with(("track-1", "track-2"))


def test_remove_saved_tracks_requires_identifiers() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    try:
        service.remove_saved_tracks([" "])
    except ValueError as exc:
        assert "identifier" in str(exc)
    else:  # pragma: no cover - sanity guard
        assert False, "Expected ValueError"
