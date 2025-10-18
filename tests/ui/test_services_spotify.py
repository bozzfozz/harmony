"""Unit tests for :mod:`app.ui.services.spotify`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Mapping
from unittest.mock import Mock

import pytest

from starlette.requests import Request

from app.ui.services.spotify import (
    SpotifyAccountSummary,
    SpotifyArtistRow,
    SpotifyRecommendationRow,
    SpotifyRecommendationSeed,
    SpotifySavedTrackRow,
    SpotifyTopArtistRow,
    SpotifyTopTrackRow,
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


def test_recommendations_normalizes_rows_and_seeds() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_recommendations.return_value = {
        "tracks": [
            {
                "id": " track-123 ",
                "name": " Example Track ",
                "artists": [
                    {"name": "Artist One"},
                    {"name": " Artist Two "},
                    99,
                ],
                "album": {"name": " Album Name "},
                "preview_url": " https://preview.example ",
            },
            {
                "id": "",
                "name": "Missing",
            },
        ],
        "seeds": [
            {
                "type": "ARTIST",
                "id": " artist-1 ",
                "initialPoolSize": "100",
                "afterFilteringSize": 80,
                "afterRelinkingSize": None,
            },
            {
                "type": "",
                "id": "ignored",
            },
        ],
    }
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    rows, seeds = service.recommendations(
        seed_tracks=[" track-1 ", "TRACK-1", "track-2"],
        seed_artists=[" artist-1 ", "ARTIST-1", "artist-2"],
        seed_genres=["rock", " Rock ", "jazz"],
        limit=200,
    )

    assert rows == (
        SpotifyRecommendationRow(
            identifier="track-123",
            name="Example Track",
            artists=("Artist One", "Artist Two"),
            album="Album Name",
            preview_url="https://preview.example",
        ),
    )
    assert seeds == (
        SpotifyRecommendationSeed(
            seed_type="artist",
            identifier="artist-1",
            initial_pool_size=100,
            after_filtering_size=80,
            after_relinking_size=None,
        ),
    )
    spotify_service.get_recommendations.assert_called_once_with(
        seed_tracks=("track-1", "track-2"),
        seed_artists=("artist-1", "artist-2"),
        seed_genres=("rock", "jazz"),
        limit=100,
    )


def test_add_tracks_to_playlist_cleans_input() -> None:
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

    count = service.add_tracks_to_playlist(
        " playlist-1 ",
        ["spotify:track:123", "spotify:track:123", "  spotify:track:456  "],
    )

    assert count == 2
    spotify_service.add_tracks_to_playlist.assert_called_once_with(
        "playlist-1",
        ("spotify:track:123", "spotify:track:456"),
    )


def test_add_tracks_to_playlist_raises_without_uris() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=Mock(),
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    with pytest.raises(ValueError):
        service.add_tracks_to_playlist("playlist-1", [])


def test_remove_tracks_from_playlist_invokes_domain() -> None:
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

    count = service.remove_tracks_from_playlist("playlist-2", ["spotify:track:abc"])

    assert count == 1
    spotify_service.remove_tracks_from_playlist.assert_called_once_with(
        "playlist-2",
        ("spotify:track:abc",),
    )


def test_remove_tracks_from_playlist_requires_playlist_id() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=Mock(),
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    with pytest.raises(ValueError):
        service.remove_tracks_from_playlist("  ", ["spotify:track:abc"])


def test_reorder_playlist_calls_domain_with_validated_positions() -> None:
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

    service.reorder_playlist("playlist-3", range_start=2, insert_before=5)

    spotify_service.reorder_playlist.assert_called_once_with(
        "playlist-3",
        range_start=2,
        insert_before=5,
    )


def test_reorder_playlist_rejects_negative_positions() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=Mock(),
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    with pytest.raises(ValueError):
        service.reorder_playlist("playlist-3", range_start=-1, insert_before=1)


def test_recommendations_clamps_limit_and_handles_empty_payload() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_recommendations.return_value = {}
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    rows, seeds = service.recommendations(limit=0)

    assert rows == ()
    assert seeds == ()
    spotify_service.get_recommendations.assert_called_once_with(
        seed_tracks=None,
        seed_artists=None,
        seed_genres=None,
        limit=1,
    )


def test_top_tracks_normalizes_payload() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_top_tracks.return_value = [
        {
            "id": "track-1",
            "name": "Track One",
            "artists": [
                {"name": "Artist One"},
                " Artist Two ",
                123,
            ],
            "album": {"name": "Album One"},
            "popularity": "87",
            "duration_ms": "195000",
        },
        {"id": None, "name": ""},
    ]
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    rows = service.top_tracks()

    assert rows == (
        SpotifyTopTrackRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist One", "Artist Two"),
            album="Album One",
            popularity=87,
            duration_ms=195000,
            rank=1,
        ),
    )
    spotify_service.get_top_tracks.assert_called_once_with(limit=20)


def test_top_artists_normalizes_payload() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_top_artists.return_value = [
        {
            "id": "artist-1",
            "name": "Artist One",
            "followers": {"total": "12000"},
            "popularity": "99",
            "genres": ["rock", " pop ", 42],
        },
        {"id": "", "name": "Unnamed"},
    ]
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    rows = service.top_artists()

    assert rows == (
        SpotifyTopArtistRow(
            identifier="artist-1",
            name="Artist One",
            followers=12000,
            popularity=99,
            genres=("rock", "pop"),
            rank=1,
        ),
    )
    spotify_service.get_top_artists.assert_called_once_with(limit=20)


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
