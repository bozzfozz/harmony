"""Unit tests for :mod:`app.ui.services.spotify`."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Mapping
from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.requests import Request

from app.integrations.contracts import ProviderAlbum, ProviderArtist, ProviderTrack
from app.services.backfill_service import BackfillJobRecord
from app.services.free_ingest_service import (
    IngestAccepted,
    IngestSkipped,
    IngestSubmission,
    InvalidPlaylistLink,
    JobCounts,
    JobStatus,
    PlaylistValidationError,
)
from app.services.spotify_domain_service import SpotifyServiceStatus
from app.ui.context import (
    build_spotify_playlist_items_context,
    build_spotify_recommendations_context,
    build_spotify_saved_tracks_context,
    build_spotify_top_tracks_context,
)
from app.ui.services.spotify import (
    SpotifyAccountSummary,
    SpotifyArtistRow,
    SpotifyBackfillSnapshot,
    SpotifyBackfillTimelineEntry,
    SpotifyFreeIngestJobSnapshot,
    SpotifyFreeIngestResult,
    SpotifyPlaylistItemRow,
    SpotifyRecommendationRow,
    SpotifyRecommendationSeed,
    SpotifySavedTrackRow,
    SpotifyTopArtistRow,
    SpotifyTopTrackRow,
    SpotifyUiService,
)
from app.utils.settings_store import read_setting, write_setting


class _StubOAuthService:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self._payload = payload
        self.reset_calls: list[None] = []

    def health(self) -> Mapping[str, object]:
        return self._payload

    def reset_scopes(self) -> None:
        self.reset_calls.append(None)


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


@pytest.mark.asyncio
async def test_list_followed_artists_normalizes_payload() -> None:
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
            "external_urls": {"spotify": "https://open.spotify.com/artist/artist-1"},
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

    rows = await service.list_followed_artists()

    assert rows == (
        SpotifyArtistRow(
            identifier="artist-1",
            name="Artist One",
            followers=43210,
            popularity=92,
            genres=("rock", "pop"),
            external_url="https://open.spotify.com/artist/artist-1",
        ),
    )
    spotify_service.get_followed_artists.assert_called_once_with()


@pytest.mark.asyncio
async def test_status_uses_executor(monkeypatch) -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    payload = SpotifyServiceStatus(
        status="connected", free_available=True, pro_available=True, authenticated=True
    )
    spotify_service.get_status.return_value = payload
    executor = AsyncMock(return_value=payload)
    monkeypatch.setattr("app.ui.services.spotify._run_in_executor", executor)
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    result = await service.status()

    assert result.status == payload.status
    executor.assert_awaited_once()
    call_args = executor.await_args
    assert call_args.args[0] is spotify_service.get_status


@pytest.mark.asyncio
async def test_account_returns_summary_with_defaults() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_current_user.return_value = {
        "display_name": "Example User",
        "id": "example-id",
        "product": "premium",
        "followers": {"total": "2500"},
        "country": "gb",
        "email": "user@example.com",
    }
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    summary = await service.account()

    assert summary == SpotifyAccountSummary(
        display_name="Example User",
        email="user@example.com",
        product="Premium",
        followers=2500,
        country="GB",
    )
    spotify_service.get_current_user.assert_called_once_with()


@pytest.mark.asyncio
async def test_account_handles_missing_profile() -> None:
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

    summary = await service.account()

    assert summary == SpotifyAccountSummary(
        display_name="user-123",
        email=None,
        product=None,
        followers=0,
        country=None,
    )


@pytest.mark.asyncio
async def test_refresh_account_clears_token_setting() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_current_user.return_value = {
        "display_name": "Example User",
        "id": "example-id",
        "product": "premium",
        "followers": {"total": 15},
        "country": "us",
        "email": "user@example.com",
    }
    oauth = _StubOAuthService({})
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=oauth,
        db_session=Mock(),
    )

    write_setting("SPOTIFY_TOKEN_INFO", '{"access_token": "value"}')

    summary = await service.refresh_account()

    assert summary == SpotifyAccountSummary(
        display_name="Example User",
        email="user@example.com",
        product="Premium",
        followers=15,
        country="US",
    )
    assert read_setting("SPOTIFY_TOKEN_INFO") is None
    assert oauth.reset_calls == []


@pytest.mark.asyncio
async def test_reset_scopes_uses_oauth_and_clears_token_setting() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_current_user.return_value = None
    oauth = _StubOAuthService({})
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=oauth,
        db_session=Mock(),
    )

    write_setting("SPOTIFY_TOKEN_INFO", '{"access_token": "value"}')

    summary = await service.reset_scopes()

    assert summary is None
    assert oauth.reset_calls == [None]
    assert read_setting("SPOTIFY_TOKEN_INFO") is None


def test_build_top_tracks_context_adds_detail_action() -> None:
    request = _make_request()
    track = SpotifyTopTrackRow(
        identifier="track-123",
        name="Example Track",
        artists=("Artist One", "Artist Two"),
        album="Example Album",
        popularity=87,
        duration_ms=185000,
        rank=1,
        external_url="https://open.spotify.com/track/track-123",
    )

    context = build_spotify_top_tracks_context(
        request,
        tracks=(track,),
        csrf_token="csrf-token",
        limit=25,
        offset=5,
        time_range="medium_term",
    )

    fragment = context["fragment"]
    table = fragment.table
    assert table.column_keys[-2] == "spotify.top_tracks.link"
    assert table.column_keys[-1] == "spotify.top_tracks.actions"
    assert table.rows, "expected at least one top track row"
    row = table.rows[0]
    link_cell = row.cells[-2]
    assert link_cell.test_id == "spotify-top-track-link-cell-track-123"
    assert link_cell.html is not None
    assert 'data-test="spotify-top-track-link-track-123"' in link_cell.html
    assert 'rel="noopener"' in link_cell.html
    action_cell = row.cells[-1]
    assert action_cell.test_id == "spotify-top-track-actions-track-123"
    assert action_cell.forms and len(action_cell.forms) == 2
    view_form, save_form = action_cell.forms
    assert view_form.action.endswith("/tracks/track-123")
    assert view_form.method == "get"
    assert view_form.hx_method == "get"
    assert view_form.hx_target == "#modal-root"
    assert view_form.submit_label_key == "spotify.track.view"
    assert save_form.action.endswith("/ui/spotify/saved/save")

    assert context["time_range"] == "medium_term"
    options = context["time_range_options"]
    assert len(options) == 3
    active = [option for option in options if option.active]
    assert active and active[0].value == "medium_term"
    assert save_form.method == "post"
    assert save_form.hx_method == "post"
    assert save_form.hx_target == "#hx-spotify-saved"
    assert save_form.hx_swap == "outerHTML"
    assert save_form.submit_label_key == "spotify.saved.save"
    assert save_form.hidden_fields == {
        "csrftoken": "csrf-token",
        "track_id": "track-123",
        "limit": "25",
        "offset": "5",
    }
    assert save_form.test_id == "spotify-top-track-save-track-123"
    assert save_form.disabled is False


def test_build_recommendations_context_adds_detail_action() -> None:
    request = _make_request()
    row = SpotifyRecommendationRow(
        identifier="track-xyz",
        name="Example Track",
        artists=("Artist One", "Artist Two"),
        album="Example Album",
        preview_url=None,
        external_url="https://open.spotify.com/track/track-xyz",
    )

    context = build_spotify_recommendations_context(
        request,
        csrf_token="csrf-token",
        rows=(row,),
        limit=50,
        offset=10,
    )

    fragment = context["fragment"]
    table = fragment.table
    assert table.column_keys == (
        "spotify.recommendations.track",
        "spotify.recommendations.artists",
        "spotify.recommendations.album",
        "spotify.recommendations.link",
        "spotify.recommendations.preview",
        "spotify.recommendations.actions",
    )
    assert table.rows, "expected at least one recommendation row"
    recommendation_row = table.rows[0]
    link_cell = recommendation_row.cells[3]
    assert link_cell.test_id == "spotify-recommendation-link-cell-track-xyz"
    assert link_cell.html is not None
    assert 'data-test="spotify-recommendation-link-track-xyz"' in link_cell.html
    assert 'rel="noopener"' in link_cell.html
    preview_cell = recommendation_row.cells[-2]
    assert preview_cell.test_id == "spotify-recommendation-preview-cell-track-xyz"
    assert preview_cell.text == "—"
    action_cell = recommendation_row.cells[-1]
    assert action_cell.forms and len(action_cell.forms) == 3
    view_form, queue_form, save_form = action_cell.forms
    assert view_form.action.endswith("/tracks/track-xyz")
    assert view_form.method == "get"
    assert view_form.hx_method == "get"
    assert view_form.hx_target == "#modal-root"
    assert view_form.submit_label_key == "spotify.track.view"
    assert queue_form.action.endswith("/ui/spotify/recommendations")
    assert queue_form.method == "post"
    assert queue_form.hx_method == "post"
    assert queue_form.hx_target == "#hx-spotify-recommendations"
    assert queue_form.hx_swap == "outerHTML"
    assert queue_form.submit_label_key == "spotify.saved.queue"
    assert queue_form.hidden_fields == {
        "csrftoken": "csrf-token",
        "action": "queue",
        "track_id": "track-xyz",
        "seed_artists": "",
        "seed_tracks": "",
        "seed_genres": "",
        "limit": "50",
    }
    assert queue_form.disabled is False
    assert save_form.action.endswith("/ui/spotify/saved/save")
    assert save_form.method == "post"
    assert save_form.hx_method == "post"
    assert save_form.hx_target == "#hx-spotify-saved"
    assert save_form.hx_swap == "outerHTML"
    assert save_form.submit_label_key == "spotify.saved.save"
    assert save_form.hidden_fields == {
        "csrftoken": "csrf-token",
        "track_id": "track-xyz",
        "limit": "50",
        "offset": "10",
    }
    assert save_form.test_id == "spotify-recommendation-save-track-xyz"
    assert save_form.disabled is False


def test_build_recommendations_context_includes_preview_player() -> None:
    request = _make_request()
    row = SpotifyRecommendationRow(
        identifier="track-abc",
        name="Preview Track",
        artists=("Preview Artist",),
        album=None,
        preview_url="https://cdn.example/track-abc.mp3",
    )

    context = build_spotify_recommendations_context(
        request,
        csrf_token="csrf-token",
        rows=(row,),
        limit=25,
        offset=0,
    )

    fragment = context["fragment"]
    table = fragment.table
    recommendation_row = table.rows[0]
    link_cell = recommendation_row.cells[3]
    assert link_cell.text == "—"
    preview_cell = recommendation_row.cells[-2]
    assert preview_cell.html is not None
    html = str(preview_cell.html)
    assert "<audio" in html
    assert "controls" in html
    assert 'data-test="spotify-recommendation-preview-track-abc"' in html
    assert "https://cdn.example/track-abc.mp3" in html


def test_build_recommendations_context_uses_seed_defaults() -> None:
    request = _make_request()
    context = build_spotify_recommendations_context(
        request,
        csrf_token="csrf-token",
        seed_defaults={
            "seed_tracks": "track-default",
            "seed_artists": "artist-default",
            "seed_genres": "genre-default",
        },
        show_admin_controls=True,
    )

    defaults = context["form_defaults"]
    assert defaults["seed_tracks"] == "track-default"
    assert defaults["seed_artists"] == "artist-default"
    assert defaults["seed_genres"] == "genre-default"
    assert context["show_admin_controls"] is True


def test_build_playlist_items_context_formats_added_timestamp() -> None:
    request = _make_request()
    row = SpotifyPlaylistItemRow(
        identifier="track-1",
        name="Example Track",
        artists=("Artist One",),
        album="Example Album",
        added_at=datetime(2024, 1, 31, 18, 45, tzinfo=UTC),
        added_by="Curator",
        is_local=False,
        metadata={},
    )

    context = build_spotify_playlist_items_context(
        request,
        playlist_id="playlist-1",
        playlist_name="Playlist",
        rows=(row,),
        total_count=1,
        limit=25,
        offset=0,
    )

    fragment = context["fragment"]
    table = fragment.table
    playlist_row = table.rows[0]
    added_cell = playlist_row.cells[3]
    assert added_cell.text == "2024-01-31 18:45"


def test_build_saved_tracks_context_formats_added_timestamp() -> None:
    request = _make_request()
    row = SpotifySavedTrackRow(
        identifier="track-1",
        name="Example Track",
        artists=("Artist One", "Artist Two"),
        album="Example Album",
        added_at=datetime(2024, 1, 31, 18, 45, tzinfo=UTC),
    )

    context = build_spotify_saved_tracks_context(
        request,
        rows=(row,),
        total_count=1,
        limit=25,
        offset=0,
        csrf_token="csrf-token",
    )

    fragment = context["fragment"]
    table = fragment.table
    saved_row = table.rows[0]
    added_cell = saved_row.cells[3]
    assert added_cell.text == "2024-01-31 18:45"


@pytest.mark.asyncio
async def test_track_detail_combines_metadata_and_features() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_track_details.return_value = {
        "id": "track-123",
        "name": "Example Track",
        "artists": [
            {"name": "Artist One"},
            {"name": "Artist Two"},
        ],
        "album": {"name": "Example Album", "release_date": "2023-09-01"},
        "duration_ms": 185000,
        "popularity": 87,
        "explicit": True,
        "preview_url": "https://preview.example/track-123",
        "external_urls": {"spotify": "https://open.spotify.com/track/track-123"},
    }
    spotify_service.get_audio_features.return_value = {
        "danceability": 0.85,
        "energy": 0.92,
        "tempo": 128.123,
        "mode": 1,
    }
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    detail = await service.track_detail(" track-123 ")

    assert detail.track_id == "track-123"
    assert detail.name == "Example Track"
    assert detail.artists == ("Artist One", "Artist Two")
    assert detail.album == "Example Album"
    assert detail.release_date == "2023-09-01"
    assert detail.duration_ms == 185000
    assert detail.popularity == 87
    assert detail.explicit is True
    assert detail.preview_url == "https://preview.example/track-123"
    assert detail.external_url == "https://open.spotify.com/track/track-123"
    assert detail.features["danceability"] == 0.85
    assert detail.features["mode"] == 1


@pytest.mark.asyncio
async def test_track_detail_handles_missing_payload() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_track_details.return_value = None
    spotify_service.get_audio_features.return_value = None
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    detail = await service.track_detail("track-999")

    assert detail.name is None
    assert detail.artists == ()
    assert detail.album is None
    assert detail.features is None


@pytest.mark.asyncio
async def test_track_detail_rejects_empty_identifier() -> None:
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
        await service.track_detail(" ")


@pytest.mark.asyncio
async def test_list_saved_tracks_normalizes_payload() -> None:
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

    rows, total = await service.list_saved_tracks(limit=1, offset=0)

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


@pytest.mark.asyncio
async def test_list_saved_tracks_applies_offset() -> None:
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

    rows, total = await service.list_saved_tracks(limit=1, offset=1)

    assert total == 2
    assert len(rows) == 1
    assert rows[0].identifier == "track-2"
    spotify_service.get_saved_tracks.assert_called_once_with(limit=1, offset=1)


@pytest.mark.asyncio
async def test_list_saved_tracks_uses_executor(monkeypatch) -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    payload = {"items": [], "total": 0}
    executor = AsyncMock(return_value=payload)
    monkeypatch.setattr("app.ui.services.spotify._run_in_executor", executor)
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    rows, total = await service.list_saved_tracks(limit=25, offset=5)

    assert rows == ()
    assert total == 0
    executor.assert_awaited_once()
    call_args = executor.await_args
    assert call_args.args[0] is spotify_service.get_saved_tracks
    assert call_args.kwargs == {"limit": 25, "offset": 5}


@pytest.mark.asyncio
async def test_playlist_items_normalizes_tracks_and_metadata() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    playlist_track = ProviderTrack(
        name=" Example Track ",
        provider="spotify",
        id=" track-1 ",
        artists=(
            ProviderArtist(source="spotify", name="Artist One"),
            ProviderArtist(source="spotify", name=" Artist Two "),
        ),
        album=ProviderAlbum(name=" Album Name "),
        metadata={
            "playlist_item": {
                "added_at": "2023-09-01T12:00:00Z",
                "is_local": True,
                "added_by": {"display_name": "Curator", "id": "user-1"},
            }
        },
    )
    spotify_service = Mock()
    spotify_service.get_playlist_items.return_value = SimpleNamespace(
        items=(playlist_track,),
        total=5,
    )
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    rows, total, page_limit, page_offset = await service.playlist_items(
        " playlist-1 ", limit=150, offset=10
    )

    assert total == 5
    assert page_limit == 100
    assert page_offset == 10
    assert rows == (
        SpotifyPlaylistItemRow(
            identifier="track-1",
            name="Example Track",
            artists=("Artist One", "Artist Two"),
            album="Album Name",
            added_at=datetime.fromisoformat("2023-09-01T12:00:00+00:00"),
            added_by="Curator",
            is_local=True,
            metadata={
                "playlist_item": {
                    "added_at": "2023-09-01T12:00:00+00:00",
                    "is_local": True,
                    "added_by": {"display_name": "Curator", "id": "user-1"},
                }
            },
        ),
    )
    spotify_service.get_playlist_items.assert_called_once_with("playlist-1", limit=100, offset=10)


@pytest.mark.asyncio
async def test_playlist_items_validates_identifier_and_applies_bounds() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_playlist_items.return_value = SimpleNamespace(items=(), total=0)
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    with pytest.raises(ValueError):
        await service.playlist_items("   ", limit=10, offset=0)

    rows, total, page_limit, page_offset = await service.playlist_items(
        "playlist-2", limit=0, offset=-5
    )

    assert rows == ()
    assert total == 0
    assert page_limit == 1
    assert page_offset == 0
    spotify_service.get_playlist_items.assert_called_once_with("playlist-2", limit=1, offset=0)


@pytest.mark.asyncio
async def test_recommendations_normalizes_rows_and_seeds() -> None:
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
                "external_urls": {"spotify": " https://open.spotify.com/track/track-123 "},
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

    seed_tracks = [" track-1 ", "TRACK-1", "track-2"]
    seed_artists = [" artist-1 ", "ARTIST-1", "artist-2"]
    seed_genres = ["rock", " Rock ", "jazz"]
    with patch("app.ui.services.spotify.log_event") as mock_log_event:
        rows, seeds = await service.recommendations(
            seed_tracks=seed_tracks,
            seed_artists=seed_artists,
            seed_genres=seed_genres,
            limit=200,
        )

    assert rows == (
        SpotifyRecommendationRow(
            identifier="track-123",
            name="Example Track",
            artists=("Artist One", "Artist Two"),
            album="Album Name",
            preview_url="https://preview.example",
            external_url="https://open.spotify.com/track/track-123",
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
    assert mock_log_event.call_count == 1
    event_args = mock_log_event.call_args
    assert event_args[0][1] == "spotify.recommendations"
    fields = event_args.kwargs
    assert fields["status"] == "ok"
    assert fields["result_tracks"] == len(rows)
    assert fields["result_seeds"] == len(seeds)
    assert fields["seed_tracks"] == len(SpotifyUiService._clean_seed_values(seed_tracks))
    assert fields["seed_artists"] == len(SpotifyUiService._clean_seed_values(seed_artists))
    assert fields["seed_genres"] == len(SpotifyUiService._clean_seed_values(seed_genres))
    assert fields["spotify.recommendations.latency_ms"] >= 0


@pytest.mark.asyncio
async def test_recommendations_clamps_limit_and_handles_empty_payload() -> None:
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

    rows, seeds = await service.recommendations(limit=0)

    assert rows == ()
    assert seeds == ()
    spotify_service.get_recommendations.assert_called_once_with(
        seed_tracks=None,
        seed_artists=None,
        seed_genres=None,
        limit=1,
    )


@pytest.mark.asyncio
async def test_top_tracks_normalizes_payload() -> None:
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
            "external_urls": {"spotify": "https://open.spotify.com/track/track-1"},
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

    rows = await service.top_tracks()

    assert rows == (
        SpotifyTopTrackRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist One", "Artist Two"),
            album="Album One",
            popularity=87,
            duration_ms=195000,
            rank=1,
            external_url="https://open.spotify.com/track/track-1",
        ),
    )
    spotify_service.get_top_tracks.assert_called_once_with(limit=20, time_range=None)


@pytest.mark.asyncio
async def test_top_tracks_honours_time_range_and_logs() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_top_tracks.return_value = []
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    with patch("app.ui.services.spotify.logger") as mock_logger:
        rows = await service.top_tracks(time_range="long_term")

    assert rows == ()
    spotify_service.get_top_tracks.assert_called_once_with(limit=20, time_range="long_term")
    mock_logger.debug.assert_called_once()
    extra = mock_logger.debug.call_args.kwargs["extra"]
    assert extra["time_range"] == "long_term"


@pytest.mark.asyncio
async def test_top_tracks_invalid_time_range_falls_back_to_default() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_top_tracks.return_value = []
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    with patch("app.ui.services.spotify.logger") as mock_logger:
        rows = await service.top_tracks(time_range="unknown")

    assert rows == ()
    spotify_service.get_top_tracks.assert_called_once_with(limit=20, time_range=None)
    mock_logger.debug.assert_called_once()
    extra = mock_logger.debug.call_args.kwargs["extra"]
    assert extra["time_range"] == "default"


@pytest.mark.asyncio
async def test_top_artists_normalizes_payload() -> None:
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
            "external_urls": {"spotify": "https://open.spotify.com/artist/artist-1"},
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

    rows = await service.top_artists()

    assert rows == (
        SpotifyTopArtistRow(
            identifier="artist-1",
            name="Artist One",
            followers=12000,
            popularity=99,
            genres=("rock", "pop"),
            rank=1,
            external_url="https://open.spotify.com/artist/artist-1",
        ),
    )
    spotify_service.get_top_artists.assert_called_once_with(limit=20, time_range=None)


@pytest.mark.asyncio
async def test_top_artists_honours_time_range() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_top_artists.return_value = []
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    with patch("app.ui.services.spotify.logger") as mock_logger:
        rows = await service.top_artists(time_range="short_term")

    assert rows == ()
    spotify_service.get_top_artists.assert_called_once_with(limit=20, time_range="short_term")
    mock_logger.debug.assert_called_once()
    extra = mock_logger.debug.call_args.kwargs["extra"]
    assert extra["time_range"] == "short_term"


@pytest.mark.asyncio
async def test_save_tracks_filters_and_returns_count() -> None:
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

    affected = await service.save_tracks([" track-1 ", "track-1", "track-2", " "])

    assert affected == 2
    spotify_service.save_tracks.assert_called_once_with(("track-1", "track-2"))


@pytest.mark.asyncio
async def test_remove_saved_tracks_requires_identifiers() -> None:
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
        await service.remove_saved_tracks([" "])
    except ValueError as exc:
        assert "identifier" in str(exc)
    else:  # pragma: no cover - sanity guard
        assert False, "Expected ValueError"


@pytest.mark.asyncio
async def test_queue_saved_tracks_formats_and_submits() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    submission = IngestSubmission(
        ok=True,
        job_id="job-queue",
        accepted=IngestAccepted(playlists=0, tracks=2, batches=1),
        skipped=IngestSkipped(playlists=0, tracks=0, reason=None),
        error=None,
    )
    spotify_service = Mock()
    spotify_service.get_track_details.side_effect = [
        {
            "name": "Track One",
            "artists": [{"name": "Artist One"}, {"name": "Artist Two"}],
            "album": {"name": "Album One"},
        },
        {
            "name": "Track Two",
            "artists": [{"name": "Artist Two"}],
            "album": {},
        },
    ]
    spotify_service.submit_free_ingest = AsyncMock(return_value=submission)
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    result = await service.queue_saved_tracks([" track-1 ", "track-2"])

    assert isinstance(result, SpotifyFreeIngestResult)
    assert result.accepted.tracks == 2
    spotify_service.get_track_details.assert_any_call("track-1")
    spotify_service.get_track_details.assert_any_call("track-2")
    spotify_service.submit_free_ingest.assert_awaited_once()
    args, kwargs = spotify_service.submit_free_ingest.await_args
    assert args == ()
    submitted_tracks = kwargs["tracks"]
    assert submitted_tracks == (
        "Artist One, Artist Two - Track One (Album One)",
        "Artist Two - Track Two",
    )


@pytest.mark.asyncio
async def test_queue_saved_tracks_rejects_when_imports_disabled() -> None:
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

    with pytest.raises(ValueError, match="imports are off"):
        await service.queue_saved_tracks(["track-1"], imports_enabled=False)

    spotify_service.get_track_details.assert_not_called()


@pytest.mark.asyncio
async def test_queue_saved_tracks_raises_when_no_metadata() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_track_details.return_value = {}
    spotify_service.submit_free_ingest = AsyncMock()
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    with pytest.raises(ValueError):
        await service.queue_saved_tracks(["missing-track"])

    spotify_service.submit_free_ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_recommendation_tracks_rejects_when_imports_disabled() -> None:
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

    with pytest.raises(ValueError, match="imports are off"):
        await service.queue_recommendation_tracks(["track-1"], imports_enabled=False)

    spotify_service.get_track_details.assert_not_called()


@pytest.mark.asyncio
async def test_free_import_success_maps_submission() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    submission = IngestSubmission(
        ok=True,
        job_id="job-1",
        accepted=IngestAccepted(playlists=2, tracks=10, batches=3),
        skipped=IngestSkipped(playlists=1, tracks=0, reason="limit"),
        error=None,
    )
    spotify_service = AsyncMock()
    spotify_service.free_import.return_value = submission
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    result = await service.free_import(
        playlist_links=["https://open.spotify.com/playlist/demo"],
        tracks=["Artist - Track"],
    )

    assert isinstance(result, SpotifyFreeIngestResult)
    assert result.ok is True
    assert result.job_id == "job-1"
    assert result.accepted.playlists == 2
    assert result.skipped.reason == "limit"
    spotify_service.free_import.assert_awaited_once()


@pytest.mark.asyncio
async def test_free_import_handles_permission_error() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = AsyncMock()
    spotify_service.free_import.side_effect = PermissionError("auth required")
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    result = await service.free_import(playlist_links=None, tracks=None)

    assert result.ok is False
    assert "Spotify authentication" in (result.error or "")
    assert result.accepted.playlists == 0
    assert result.skipped.playlists == 0
    spotify_service.free_import.assert_awaited_once()


@pytest.mark.asyncio
async def test_free_import_handles_unexpected_error() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = AsyncMock()
    spotify_service.free_import.side_effect = RuntimeError("boom")
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    result = await service.free_import(playlist_links=None, tracks=None)

    assert result.ok is False
    assert result.error == "Failed to enqueue the ingest job."
    assert result.skipped.playlists == 0
    spotify_service.free_import.assert_awaited_once()


@pytest.mark.asyncio
async def test_free_ingest_job_status_returns_none_without_job_id() -> None:
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

    assert await service.free_ingest_job_status(None) is None
    spotify_service.get_free_ingest_job.assert_not_called()


@pytest.mark.asyncio
async def test_free_ingest_job_status_returns_none_on_error() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_free_ingest_job.side_effect = RuntimeError("boom")
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    assert await service.free_ingest_job_status("job-404") is None
    spotify_service.get_free_ingest_job.assert_called_once_with("job-404")


@pytest.mark.asyncio
async def test_submit_free_ingest_handles_validation_error() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = AsyncMock()
    spotify_service.submit_free_ingest.side_effect = PlaylistValidationError(
        [InvalidPlaylistLink(url="https://bad", reason="INVALID_SCHEME")]
    )
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    result = await service.submit_free_ingest(playlist_links=["https://bad"])

    assert result.ok is False
    assert result.error is not None and "Invalid playlist links" in result.error
    assert result.skipped.playlists == 1
    spotify_service.submit_free_ingest.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_backfill_respects_cache_toggle() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.is_authenticated.return_value = True
    job = SimpleNamespace(
        id="job-2",
        limit=25,
        expand_playlists=False,
        include_cached_results=False,
    )
    spotify_service.create_backfill_job.return_value = job
    spotify_service.enqueue_backfill = AsyncMock()
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    job_id = await service.run_backfill(
        max_items=25,
        expand_playlists=False,
        include_cached_results=False,
    )

    assert job_id == "job-2"
    spotify_service.create_backfill_job.assert_called_once_with(
        max_items=25,
        expand_playlists=False,
        include_cached_results=False,
    )
    spotify_service.enqueue_backfill.assert_awaited_once_with(job)


@pytest.mark.asyncio
async def test_build_backfill_snapshot_uses_include_cached_flag() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=400))
    spotify_service = Mock()
    spotify_service.is_authenticated.return_value = True
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    payload = {
        "id": "job-5",
        "state": "running",
        "requested": 10,
        "processed": 5,
        "matched": 2,
        "cache_hits": 1,
        "cache_misses": 4,
        "expanded_playlists": 0,
        "expanded_tracks": 0,
        "duration_ms": 2500,
        "error": None,
        "expand_playlists": False,
        "include_cached_results": False,
    }

    snapshot = await service.build_backfill_snapshot(
        csrf_token="csrf",
        job_id="job-5",
        status_payload=payload,
    )

    assert isinstance(snapshot, SpotifyBackfillSnapshot)
    assert snapshot.include_cached_results is False
    cache_option = next(
        option for option in snapshot.options if option.name == "include_cached_results"
    )
    assert cache_option.checked is False


@pytest.mark.asyncio
async def test_build_backfill_snapshot_defaults_include_cached() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.is_authenticated.return_value = True
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    snapshot = await service.build_backfill_snapshot(
        csrf_token="csrf",
        job_id=None,
        status_payload=None,
    )

    assert snapshot.include_cached_results is True
    cache_option = next(
        option for option in snapshot.options if option.name == "include_cached_results"
    )
    assert cache_option.checked is True


@pytest.mark.asyncio
async def test_backfill_timeline_surfaces_include_cached() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    record = BackfillJobRecord(
        id="job-6",
        state="completed",
        requested_items=12,
        processed_items=12,
        matched_items=10,
        cache_hits=8,
        cache_misses=4,
        expanded_playlists=1,
        expanded_tracks=5,
        expand_playlists=True,
        include_cached_results=False,
        duration_ms=3200,
        error=None,
        created_at=datetime(2023, 8, 1, 12, 0),
        updated_at=datetime(2023, 8, 1, 12, 5),
    )
    spotify_service = Mock()
    spotify_service.list_backfill_jobs.return_value = (record,)
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    timeline = await service.backfill_timeline(limit=5)

    assert len(timeline) == 1
    entry = timeline[0]
    assert isinstance(entry, SpotifyBackfillTimelineEntry)
    assert entry.include_cached_results is False
    spotify_service.list_backfill_jobs.assert_called_once_with(limit=5)


@pytest.mark.asyncio
async def test_backfill_status_includes_cache_flag() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    status_payload = SimpleNamespace(
        id="job-7",
        state="queued",
        requested_items=3,
        processed_items=0,
        matched_items=0,
        cache_hits=0,
        cache_misses=0,
        expanded_playlists=0,
        expanded_tracks=0,
        duration_ms=None,
        error=None,
        expand_playlists=True,
        include_cached_results=False,
    )
    spotify_service = Mock()
    spotify_service.get_backfill_status.return_value = status_payload
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    payload = await service.backfill_status("job-7")

    assert payload is not None
    assert payload["include_cached_results"] is False
    spotify_service.get_backfill_status.assert_called_once_with("job-7")


@pytest.mark.asyncio
async def test_free_ingest_job_status_converts_snapshot() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    job_status = JobStatus(
        id="job-9",
        state="running",
        counts=JobCounts(registered=5, normalized=4, queued=3, completed=2, failed=1),
        accepted=IngestAccepted(playlists=1, tracks=2, batches=1),
        skipped=IngestSkipped(playlists=0, tracks=1, reason="invalid"),
        error="warning",
        queued_tracks=5,
        failed_tracks=1,
        skipped_tracks=2,
        skip_reason="invalid",
    )
    spotify_service = Mock()
    spotify_service.get_free_ingest_job.return_value = job_status
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    snapshot = await service.free_ingest_job_status("job-9")

    assert isinstance(snapshot, SpotifyFreeIngestJobSnapshot)
    assert snapshot.job_id == "job-9"
    assert snapshot.counts.completed == 2
    assert snapshot.accepted.tracks == 2
    assert snapshot.skipped.reason == "invalid"
    spotify_service.get_free_ingest_job.assert_called_once_with("job-9")
