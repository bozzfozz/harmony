from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
import json
import re
from types import SimpleNamespace
from typing import Any, Sequence
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from app.api.search import DEFAULT_SOURCES
from app.config import SecurityConfig, SoulseekConfig
from app.db import get_session, init_db, session_scope
from app.dependencies import get_download_service, get_soulseek_client
from app.errors import AppError, ErrorCode, ValidationAppError
from app.integrations.health import IntegrationHealth, ProviderHealth
from app.main import app
from app.models import Download
from app.schemas import StatusResponse
from app.services.download_service import DownloadService
from app.services.watchlist_service import WatchlistService
from app.ui.services import (
    ActivityPage,
    DownloadPage,
    DownloadRow,
    OrchestratorJob,
    SearchResult,
    SearchResultDownload,
    SearchResultsPage,
    SoulseekUiService,
    SoulseekUploadRow,
    SoulseekUserBrowsingStatus,
    SoulseekUserDirectoryEntry,
    SoulseekUserDirectoryListing,
    SoulseekUserFileEntry,
    SoulseekUserProfile,
    SoulseekUserStatus,
    SpotifyAccountSummary,
    SpotifyArtistRow,
    SpotifyBackfillOption,
    SpotifyBackfillSnapshot,
    SpotifyBackfillTimelineEntry,
    SpotifyFreeIngestAccepted,
    SpotifyFreeIngestJobCounts,
    SpotifyFreeIngestJobSnapshot,
    SpotifyFreeIngestResult,
    SpotifyFreeIngestSkipped,
    SpotifyManualResult,
    SpotifyOAuthHealth,
    SpotifyPlaylistFilterOption,
    SpotifyPlaylistFilters,
    SpotifyPlaylistItemRow,
    SpotifyPlaylistRow,
    SpotifyRecommendationRow,
    SpotifyRecommendationSeed,
    SpotifySavedTrackRow,
    SpotifyStatus,
    SpotifyTopArtistRow,
    SpotifyTopTrackRow,
    SpotifyTrackDetail,
    SpotifyUiService,
    WatchlistRow,
    WatchlistTable,
    get_activity_ui_service,
    get_downloads_ui_service,
    get_search_ui_service,
    get_soulseek_ui_service,
    get_spotify_ui_service,
    get_watchlist_ui_service,
)
from app.ui.session import fingerprint_api_key
from app.utils.activity import activity_manager
from tests.ui.test_ui_auth import _assert_html_response, _cookie_header, _create_client


def _cookies_header(client: TestClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


class _StubOAuthService:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self._payload = payload

    def health(self) -> Mapping[str, object]:
        return self._payload

    def reset_scopes(self) -> None:  # pragma: no cover - trivial stub
        return None


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


def _login(client: TestClient, api_key: str = "primary-key") -> None:
    response = client.post("/ui/login", data={"api_key": api_key}, follow_redirects=False)
    assert response.status_code == 303


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _csrf_headers(client: TestClient) -> dict[str, str]:
    dashboard = client.get("/ui/", headers={"Cookie": _cookies_header(client)})
    _assert_html_response(dashboard)
    token = _extract_csrf_token(dashboard.text)
    return {
        "Cookie": _cookies_header(client),
        "X-CSRF-Token": token,
    }


def _assert_json_error(response, *, status_code: int) -> None:
    assert response.status_code == status_code
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("application/json"), content_type


def _assert_button_enabled(html: str, data_test: str) -> None:
    assert f'data-test="{data_test}"' in html
    pattern = rf'data-test="{re.escape(data_test)}"[^>]*disabled'
    assert re.search(pattern, html) is None


def _assert_button_disabled(html: str, data_test: str) -> None:
    assert f'data-test="{data_test}"' in html
    pattern = rf'data-test="{re.escape(data_test)}"[^>]*disabled'
    assert re.search(pattern, html) is not None


def _read_only_env() -> dict[str, str]:
    fingerprint = fingerprint_api_key("primary-key")
    return {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}


def _admin_env() -> dict[str, str]:
    fingerprint = fingerprint_api_key("primary-key")
    return {"UI_ROLE_OVERRIDES": f"{fingerprint}:admin"}


@pytest.mark.parametrize(
    "path",
    (
        "/ui/soulseek/status",
        "/ui/soulseek/config",
        "/ui/soulseek/uploads",
        "/ui/soulseek/downloads",
        "/ui/soulseek/user/info",
        "/ui/soulseek/user/directory",
    ),
)
def test_soulseek_fragments_forbidden_for_read_only(monkeypatch, path: str) -> None:
    with _create_client(monkeypatch, extra_env=_read_only_env()) as client:
        _login(client)
        response = client.get(path, headers={"Cookie": _cookies_header(client)})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.headers.get("content-type", "").startswith("application/json")


class _StubActivityService:
    def __init__(self, page: ActivityPage | None = None) -> None:
        default_page = ActivityPage(
            items=(),
            limit=50,
            offset=0,
            total_count=0,
            type_filter=None,
            status_filter=None,
        )
        self.page = page or default_page
        self.exception: Exception | None = None
        self.calls: list[tuple[int, int, str | None, str | None]] = []

    def list_activity(
        self,
        *,
        limit: int,
        offset: int,
        type_filter: str | None,
        status_filter: str | None,
    ) -> ActivityPage:
        self.calls.append((limit, offset, type_filter, status_filter))
        if self.exception:
            raise self.exception
        return self.page

    async def list_activity_async(
        self,
        *,
        limit: int,
        offset: int,
        type_filter: str | None,
        status_filter: str | None,
    ) -> ActivityPage:
        return self.list_activity(
            limit=limit,
            offset=offset,
            type_filter=type_filter,
            status_filter=status_filter,
        )


class _RecordingDownloadsService:
    def __init__(self, page: DownloadPage) -> None:
        page.items = list(page.items)
        self.page = page
        self.list_exception: Exception | None = None
        self.update_exception: Exception | None = None
        self.updated: list[tuple[int, int]] = []
        self.retry_exception: Exception | None = None
        self.cancel_exception: Exception | None = None
        self.export_exception: Exception | None = None
        self.retried: list[int] = []
        self.cancelled: list[int] = []
        self.export_calls: list[dict[str, Any]] = []
        self.export_response: PlainTextResponse | None = None

    def list_downloads(
        self,
        *,
        limit: int,
        offset: int,
        include_all: bool,
        status_filter: str | None,
    ) -> DownloadPage:
        if self.list_exception:
            raise self.list_exception
        return self.page

    async def list_downloads_async(
        self,
        *,
        limit: int,
        offset: int,
        include_all: bool,
        status_filter: str | None,
    ) -> DownloadPage:
        return self.list_downloads(
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=status_filter,
        )

    def update_priority(self, *, download_id: int, priority: int) -> DownloadRow:
        if self.update_exception:
            raise self.update_exception
        self.updated.append((download_id, priority))
        new_row = None
        for index, row in enumerate(self.page.items):
            if row.identifier == download_id:
                new_row = replace(row, priority=priority)
                self.page.items[index] = new_row
                break
        if new_row is None:
            new_row = DownloadRow(
                identifier=download_id,
                filename="",
                status="queued",
                progress=None,
                priority=priority,
                username=None,
                created_at=None,
                updated_at=None,
                organized_path=None,
                lyrics_status=None,
                has_lyrics=False,
                lyrics_path=None,
                artwork_status=None,
                has_artwork=False,
                artwork_path=None,
            )
        return new_row

    async def retry_download(
        self,
        *,
        download_id: int,
        limit: int,
        offset: int,
        include_all: bool,
        status_filter: str | None,
    ) -> DownloadPage:
        if self.retry_exception:
            raise self.retry_exception
        self.retried.append(download_id)
        return self.list_downloads(
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=status_filter,
        )

    async def cancel_download(
        self,
        *,
        download_id: int,
        limit: int,
        offset: int,
        include_all: bool,
        status_filter: str | None,
    ) -> DownloadPage:
        if self.cancel_exception:
            raise self.cancel_exception
        self.cancelled.append(download_id)
        self.page.items = [row for row in self.page.items if row.identifier != download_id]
        return self.list_downloads(
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=status_filter,
        )

    def export_downloads(
        self,
        *,
        format: str,
        status_filter: str | None,
        from_time: str | None = None,
        to_time: str | None = None,
    ) -> PlainTextResponse:
        if self.export_exception:
            raise self.export_exception
        self.export_calls.append(
            {
                "format": format,
                "status_filter": status_filter,
                "from": from_time,
                "to": to_time,
            }
        )
        if self.export_response is not None:
            return self.export_response
        return PlainTextResponse("id,filename\n", media_type="text/csv")


@pytest.mark.asyncio
async def test_download_service_handles_running_event_loop() -> None:
    init_db()
    with session_scope() as session:
        download = Download(
            filename="loop.flac",
            state="queued",
            progress=0.5,
            priority=4,
            username="tester",
        )
        session.add(download)
        session.flush()
        download_id = download.id

    class _StubTransfersApi:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def get_download_queue(self, identifier: int) -> dict[str, Any]:
            self.calls.append(identifier)
            return {"status": "running", "download_id": identifier}

    transfers = _StubTransfersApi()
    db_session = get_session()

    async def _runner(func):
        return func(db_session)

    service = DownloadService(
        session=db_session,
        session_runner=_runner,
        transfers=transfers,
    )

    try:
        records = service.list_downloads(
            include_all=True,
            status_filter=None,
            limit=10,
            offset=0,
        )
    finally:
        db_session.close()

    assert transfers.calls == [download_id]
    assert getattr(records[0], "live_queue", None) == {
        "status": "running",
        "download_id": download_id,
    }


class _StubDbSession:
    def __init__(self, download) -> None:
        self._download = download

    def get(self, model, identifier):  # pragma: no cover - simple stub
        if identifier == getattr(self._download, "id", None):
            return self._download
        return None


class _StubSessionContext:
    def __init__(self, session) -> None:
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _make_discography_job(
    identifier: int,
    *,
    artist_id: str | None = None,
    artist_name: str | None = None,
    status: str = "queued",
) -> SimpleNamespace:
    created = datetime(2024, 1, 1, tzinfo=UTC)
    updated = datetime(2024, 1, 2, tzinfo=UTC)
    return SimpleNamespace(
        id=identifier,
        artist_id=artist_id or f"soulseek:{identifier}",
        artist_name=artist_name or f"Artist {identifier}",
        status=status,
        created_at=created,
        updated_at=updated,
    )


class _StubSearchService:
    def __init__(self, result: SearchResultsPage | Exception) -> None:
        self._result = result
        self.calls: list[tuple[str, int, int, Sequence[str]]] = []

    async def search(
        self,
        request,
        *,
        query: str,
        limit: int,
        offset: int,
        sources: Sequence[str] | None = None,
    ) -> SearchResultsPage:
        if isinstance(self._result, Exception):
            raise self._result
        self.calls.append((query, limit, offset, tuple(sources or [])))
        return self._result


class _StubQueueDownloadService:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self._result = result
        self.calls: list[tuple[Any, Any]] = []

    async def queue_downloads(self, payload, *, worker: Any) -> dict[str, Any]:
        self.calls.append((payload, worker))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _StubSpotifyService:
    def __init__(self) -> None:
        self._status = SpotifyStatus(
            status="connected",
            free_available=True,
            pro_available=True,
            authenticated=True,
        )
        self._oauth = SpotifyOAuthHealth(
            manual_enabled=True,
            redirect_uri="http://localhost/callback",
            public_host_hint=None,
            active_transactions=0,
            ttl_seconds=300,
        )
        self.account_summary: SpotifyAccountSummary | None = SpotifyAccountSummary(
            display_name="Stub User",
            email="stub@example.com",
            product="Premium",
            followers=1200,
            country="US",
        )
        self.account_exception: Exception | None = None
        self.playlists: Sequence[SpotifyPlaylistRow] | Exception = ()
        self.filter_options = SpotifyPlaylistFilters(
            owners=(),
            sync_statuses=(),
        )
        self.playlist_filters_exception: Exception | None = None
        self.refresh_calls: list[None] = []
        self.force_sync_calls: list[None] = []
        self.list_playlists_calls: list[tuple[str | None, str | None]] = []
        self.playlist_items_rows: Sequence[SpotifyPlaylistItemRow] | Exception = ()
        self.playlist_items_total: int = 0
        self.playlist_items_page_limit: int = 25
        self.playlist_items_page_offset: int = 0
        self.playlist_items_calls: list[tuple[str, int, int]] = []
        self.playlist_items_exception: Exception | None = None
        self.artists: Sequence[SpotifyArtistRow] | Exception = ()
        self.top_tracks_rows: Sequence[SpotifyTopTrackRow] | Exception = (
            SpotifyTopTrackRow(
                identifier="top-track-1",
                name="Top Track",
                artists=("Top Artist",),
                album="Top Album",
                popularity=98,
                duration_ms=180000,
                rank=1,
                external_url="https://open.spotify.com/track/top-track-1",
            ),
        )
        self.top_artists_rows: Sequence[SpotifyTopArtistRow] | Exception = (
            SpotifyTopArtistRow(
                identifier="top-artist-1",
                name="Top Artist",
                followers=321000,
                popularity=99,
                genres=("rock",),
                rank=1,
                external_url="https://open.spotify.com/artist/top-artist-1",
            ),
        )
        self.recommendation_rows: Sequence[SpotifyRecommendationRow] = (
            SpotifyRecommendationRow(
                identifier="track-reco-1",
                name="Recommended Track",
                artists=("Reco Artist",),
                album="Reco Album",
                preview_url=None,
                external_url="https://open.spotify.com/track/track-reco-1",
            ),
        )
        self.recommendation_seeds: Sequence[SpotifyRecommendationSeed] = (
            SpotifyRecommendationSeed(
                seed_type="artist",
                identifier="artist-seed-1",
                initial_pool_size=50,
                after_filtering_size=40,
                after_relinking_size=30,
            ),
        )
        self.recommendations_calls: list[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], int]
        ] = []
        self.recommendations_exception: Exception | None = None
        self.saved_tracks_rows: list[SpotifySavedTrackRow] = [
            SpotifySavedTrackRow(
                identifier="track-1",
                name="Track One",
                artists=("Artist One",),
                album="Album One",
                added_at=datetime(2023, 9, 1, 12, 0),
            )
        ]
        self.saved_tracks_total: int | None = len(self.saved_tracks_rows)
        self.saved_tracks_exception: Exception | None = None
        self.track_detail_result = SpotifyTrackDetail(
            track_id="track-1",
            name="Track One",
            artists=("Artist One",),
            album="Album One",
            release_date="2023-09-01",
            duration_ms=185000,
            popularity=80,
            explicit=False,
            preview_url=None,
            external_url=None,
            detail={},
            features={},
        )
        self.track_detail_exception: Exception | None = None
        self.track_detail_calls: list[str] = []
        self.manual_result = SpotifyManualResult(ok=True, message="Completed")
        self.manual_exception: Exception | None = None
        self.start_url = "https://spotify.example/auth"
        self.start_exception: Exception | None = None
        self.backfill_status_payload: Mapping[str, object] | None = None
        self.snapshot = SpotifyBackfillSnapshot(
            csrf_token="token",
            can_run=True,
            default_max_items=100,
            expand_playlists=True,
            include_cached_results=True,
            options=(
                SpotifyBackfillOption(
                    name="expand_playlists",
                    label_key="spotify.backfill.options.expand_playlists",
                    description_key="spotify.backfill.options.expand_playlists_hint",
                    checked=True,
                ),
                SpotifyBackfillOption(
                    name="include_cached_results",
                    label_key="spotify.backfill.options.include_cached",
                    description_key="spotify.backfill.options.include_cached_hint",
                    checked=True,
                ),
            ),
            last_job_id="job-1",
            state="queued",
            requested=10,
            processed=0,
            matched=0,
            cache_hits=0,
            cache_misses=0,
            expanded_playlists=0,
            expanded_tracks=0,
            duration_ms=None,
            error=None,
            can_pause=True,
            can_resume=False,
            can_cancel=True,
        )
        self.run_backfill_job_id = "job-1"
        self.refresh_account_calls: list[None] = []
        self.reset_scopes_calls: list[None] = []
        self.run_backfill_exception: Exception | None = None
        self.manual_calls: list[str] = []
        self.backfill_snapshot_calls: list[tuple[str, str | None, Mapping[str, object] | None]] = []
        self.backfill_status_calls: list[str | None] = []
        self.run_calls: list[tuple[int | None, bool, bool]] = []
        self.pause_backfill_calls: list[str] = []
        self.resume_backfill_calls: list[str] = []
        self.cancel_backfill_calls: list[str] = []
        self.pause_backfill_exception: Exception | None = None
        self.resume_backfill_exception: Exception | None = None
        self.cancel_backfill_exception: Exception | None = None
        self.pause_backfill_result: Mapping[str, object] | None = None
        self.resume_backfill_result: Mapping[str, object] | None = None
        self.cancel_backfill_result: Mapping[str, object] | None = None
        self.backfill_timeline_entries: tuple[SpotifyBackfillTimelineEntry, ...] = ()
        self.backfill_timeline_calls: list[int] = []
        self.list_saved_calls: list[tuple[int, int]] = []
        self.top_tracks_calls: list[tuple[int, str | None]] = []
        self.top_artists_calls: list[tuple[int, str | None]] = []
        self.save_calls: list[tuple[str, ...]] = []
        self.remove_calls: list[tuple[str, ...]] = []
        self.queue_calls: list[tuple[str, ...]] = []
        self.save_exception: Exception | None = None
        self.remove_exception: Exception | None = None
        self.queue_exception: Exception | None = None
        self.free_ingest_submit_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self.free_ingest_submit_result = SpotifyFreeIngestResult(
            ok=False,
            job_id=None,
            accepted=SpotifyFreeIngestAccepted(playlists=0, tracks=0, batches=0),
            skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
            error="",
        )
        self.queue_result = SpotifyFreeIngestResult(
            ok=True,
            job_id="job-queue",
            accepted=SpotifyFreeIngestAccepted(playlists=0, tracks=1, batches=1),
            skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
            error=None,
        )
        self.free_ingest_submit_exception: Exception | None = None
        self.free_import_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self.free_import_result = SpotifyFreeIngestResult(
            ok=True,
            job_id="job-free",
            accepted=SpotifyFreeIngestAccepted(playlists=1, tracks=2, batches=1),
            skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
            error=None,
        )
        self.free_import_exception: Exception | None = None
        self.free_ingest_status_calls: list[str | None] = []
        self.free_ingest_status_result: SpotifyFreeIngestJobSnapshot | None = None
        self.free_upload_calls: list[tuple[str, bytes]] = []
        self.free_upload_result: SpotifyFreeIngestResult | None = None
        self.free_upload_exception: Exception | None = None
        self.free_upload_tracks: tuple[str, ...] = ("Artist - Track",)
        self._free_ingest_result_store: SpotifyFreeIngestResult | None = None
        self._free_ingest_error_store: str | None = None
        self.recommendation_seed_defaults: dict[str, str] = {}
        self.save_seed_defaults_calls: list[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]
        ] = []
        self.queue_recommendation_calls: list[tuple[str, ...]] = []
        self.queue_recommendation_exception: Exception | None = None

    async def status(self) -> SpotifyStatus:
        return self._status

    def oauth_health(self) -> SpotifyOAuthHealth:
        return self._oauth

    async def list_playlists(
        self,
        *,
        owner: str | None = None,
        sync_status: str | None = None,
    ) -> Sequence[SpotifyPlaylistRow]:
        if isinstance(self.playlists, Exception):
            raise self.playlists
        self.list_playlists_calls.append((owner, sync_status))
        return tuple(self.playlists)

    async def playlist_filters(self) -> SpotifyPlaylistFilters:
        if self.playlist_filters_exception:
            raise self.playlist_filters_exception
        return self.filter_options

    async def refresh_playlists(self) -> None:
        self.refresh_calls.append(None)

    async def force_sync_playlists(self) -> None:
        self.force_sync_calls.append(None)

    async def playlist_items(
        self, playlist_id: str, *, limit: int, offset: int
    ) -> tuple[Sequence[SpotifyPlaylistItemRow], int, int, int]:
        self.playlist_items_calls.append((playlist_id, limit, offset))
        if self.playlist_items_exception:
            raise self.playlist_items_exception
        if isinstance(self.playlist_items_rows, Exception):
            raise self.playlist_items_rows
        return (
            tuple(self.playlist_items_rows),
            self.playlist_items_total,
            self.playlist_items_page_limit,
            self.playlist_items_page_offset,
        )

    async def list_followed_artists(self) -> Sequence[SpotifyArtistRow]:
        if isinstance(self.artists, Exception):
            raise self.artists
        return tuple(self.artists)

    async def top_tracks(
        self,
        *,
        limit: int = 20,
        time_range: str | None = None,
    ) -> Sequence[SpotifyTopTrackRow]:
        self.top_tracks_calls.append((limit, time_range))
        if isinstance(self.top_tracks_rows, Exception):
            raise self.top_tracks_rows
        return tuple(self.top_tracks_rows)

    async def top_artists(
        self,
        *,
        limit: int = 20,
        time_range: str | None = None,
    ) -> Sequence[SpotifyTopArtistRow]:
        self.top_artists_calls.append((limit, time_range))
        if isinstance(self.top_artists_rows, Exception):
            raise self.top_artists_rows
        return tuple(self.top_artists_rows)

    async def recommendations(
        self,
        *,
        seed_tracks: Sequence[str] | None = None,
        seed_artists: Sequence[str] | None = None,
        seed_genres: Sequence[str] | None = None,
        limit: int = 20,
    ) -> tuple[Sequence[SpotifyRecommendationRow], Sequence[SpotifyRecommendationSeed]]:
        self.recommendations_calls.append(
            (
                tuple(seed_tracks or ()),
                tuple(seed_artists or ()),
                tuple(seed_genres or ()),
                limit,
            )
        )
        if self.recommendations_exception:
            raise self.recommendations_exception
        return tuple(self.recommendation_rows), tuple(self.recommendation_seeds)

    def get_recommendation_seed_defaults(self) -> Mapping[str, str]:
        return dict(self.recommendation_seed_defaults)

    def save_recommendation_seed_defaults(
        self,
        *,
        seed_tracks: Sequence[str],
        seed_artists: Sequence[str],
        seed_genres: Sequence[str],
    ) -> Mapping[str, str]:
        record = (tuple(seed_tracks), tuple(seed_artists), tuple(seed_genres))
        self.save_seed_defaults_calls.append(record)
        self.recommendation_seed_defaults = {
            "seed_tracks": ", ".join(seed_tracks),
            "seed_artists": ", ".join(seed_artists),
            "seed_genres": ", ".join(seed_genres),
        }
        return dict(self.recommendation_seed_defaults)

    async def queue_recommendation_tracks(
        self, track_ids: Sequence[str], *, imports_enabled: bool = True
    ) -> SpotifyFreeIngestResult:
        self.queue_recommendation_calls.append(tuple(track_ids))
        if self.queue_recommendation_exception:
            exc = self.queue_recommendation_exception
            if isinstance(exc, AppError):
                raise exc
            raise exc
        return self.queue_result

    async def list_saved_tracks(
        self, *, limit: int, offset: int
    ) -> tuple[Sequence[SpotifySavedTrackRow], int]:
        self.list_saved_calls.append((limit, offset))
        if self.saved_tracks_exception:
            raise self.saved_tracks_exception
        total = (
            self.saved_tracks_total
            if self.saved_tracks_total is not None
            else len(self.saved_tracks_rows)
        )
        start = max(0, min(offset, len(self.saved_tracks_rows)))
        end = max(start, min(start + max(limit, 0), len(self.saved_tracks_rows)))
        return tuple(self.saved_tracks_rows[start:end]), total

    async def track_detail(self, track_id: str) -> SpotifyTrackDetail:
        self.track_detail_calls.append(track_id)
        if self.track_detail_exception:
            raise self.track_detail_exception
        return self.track_detail_result

    async def account(self) -> SpotifyAccountSummary | None:
        if self.account_exception:
            raise self.account_exception
        return self.account_summary

    async def refresh_account(self) -> SpotifyAccountSummary | None:
        self.refresh_account_calls.append(None)
        return await self.account()

    async def reset_scopes(self) -> SpotifyAccountSummary | None:
        self.reset_scopes_calls.append(None)
        return await self.account()

    async def manual_complete(self, *, redirect_url: str) -> SpotifyManualResult:
        if self.manual_exception:
            raise self.manual_exception
        self.manual_calls.append(redirect_url)
        return self.manual_result

    def start_oauth(self) -> str:
        if self.start_exception:
            raise self.start_exception
        return self.start_url

    async def run_backfill(
        self,
        *,
        max_items: int | None,
        expand_playlists: bool,
        include_cached_results: bool,
    ) -> str:
        if self.run_backfill_exception:
            raise self.run_backfill_exception
        self.run_calls.append((max_items, expand_playlists, include_cached_results))
        return self.run_backfill_job_id

    async def save_tracks(self, track_ids: Sequence[str]) -> int:
        if self.save_exception:
            raise self.save_exception
        cleaned = tuple(track_ids)
        self.save_calls.append(cleaned)
        for track_id in cleaned:
            self.saved_tracks_rows.insert(
                0,
                SpotifySavedTrackRow(
                    identifier=track_id,
                    name=f"Track {track_id}",
                    artists=tuple(),
                    album=None,
                    added_at=None,
                ),
            )
        self.saved_tracks_total = len(self.saved_tracks_rows)
        return len(cleaned)

    async def remove_saved_tracks(self, track_ids: Sequence[str]) -> int:
        if self.remove_exception:
            raise self.remove_exception
        cleaned = tuple(track_ids)
        self.remove_calls.append(cleaned)
        remaining = [row for row in self.saved_tracks_rows if row.identifier not in cleaned]
        removed = len(self.saved_tracks_rows) - len(remaining)
        self.saved_tracks_rows = remaining
        self.saved_tracks_total = len(self.saved_tracks_rows)
        return removed

    async def queue_saved_tracks(
        self, track_ids: Sequence[str], *, imports_enabled: bool = True
    ) -> SpotifyFreeIngestResult:
        if self.queue_exception:
            raise self.queue_exception
        cleaned = tuple(track_ids)
        self.queue_calls.append(cleaned)
        return self.queue_result

    async def backfill_status(self, job_id: str | None) -> Mapping[str, object] | None:
        self.backfill_status_calls.append(job_id)
        return self.backfill_status_payload

    async def build_backfill_snapshot(
        self,
        *,
        csrf_token: str,
        job_id: str | None,
        status_payload: Mapping[str, object] | None,
    ) -> SpotifyBackfillSnapshot:
        self.backfill_snapshot_calls.append((csrf_token, job_id, status_payload))
        return self.snapshot

    async def pause_backfill(self, job_id: str) -> Mapping[str, object]:
        self.pause_backfill_calls.append(job_id)
        if self.pause_backfill_exception:
            raise self.pause_backfill_exception
        return self.pause_backfill_result or self._default_backfill_payload(job_id, "paused")

    async def resume_backfill(self, job_id: str) -> Mapping[str, object]:
        self.resume_backfill_calls.append(job_id)
        if self.resume_backfill_exception:
            raise self.resume_backfill_exception
        return self.resume_backfill_result or self._default_backfill_payload(job_id, "queued")

    async def cancel_backfill(self, job_id: str) -> Mapping[str, object]:
        self.cancel_backfill_calls.append(job_id)
        if self.cancel_backfill_exception:
            raise self.cancel_backfill_exception
        return self.cancel_backfill_result or self._default_backfill_payload(job_id, "cancelled")

    async def backfill_timeline(self, *, limit: int = 10) -> Sequence[SpotifyBackfillTimelineEntry]:
        self.backfill_timeline_calls.append(limit)
        return tuple(self.backfill_timeline_entries)

    @staticmethod
    def _default_backfill_payload(job_id: str, state: str) -> Mapping[str, object]:
        return {
            "id": job_id,
            "state": state,
            "requested": 5,
            "processed": 1,
            "matched": 1,
            "cache_hits": 1,
            "cache_misses": 0,
            "expanded_playlists": 0,
            "expanded_tracks": 0,
            "duration_ms": 1000,
            "error": None,
            "expand_playlists": True,
            "include_cached_results": True,
        }

    async def submit_free_ingest(
        self,
        *,
        playlist_links: Sequence[str] | None = None,
        tracks: Sequence[str] | None = None,
        batch_hint: int | None = None,
    ) -> SpotifyFreeIngestResult:
        self.free_ingest_submit_calls.append((tuple(playlist_links or ()), tuple(tracks or ())))
        if self.free_ingest_submit_exception:
            raise self.free_ingest_submit_exception
        self._free_ingest_result_store = self.free_ingest_submit_result
        self._free_ingest_error_store = self.free_ingest_submit_result.error
        return self.free_ingest_submit_result

    async def free_import(
        self,
        *,
        playlist_links: Sequence[str] | None = None,
        tracks: Sequence[str] | None = None,
        batch_hint: int | None = None,
    ) -> SpotifyFreeIngestResult:
        self.free_import_calls.append((tuple(playlist_links or ()), tuple(tracks or ())))
        if self.free_import_exception:
            raise self.free_import_exception
        self._free_ingest_result_store = self.free_import_result
        self._free_ingest_error_store = self.free_import_result.error
        return self.free_import_result

    async def upload_free_ingest_file(
        self,
        *,
        filename: str,
        content: bytes,
    ) -> SpotifyFreeIngestResult:
        self.free_upload_calls.append((filename, content))
        if self.free_upload_exception:
            self._free_ingest_error_store = str(self.free_upload_exception)
            raise self.free_upload_exception
        if self.free_upload_result is not None:
            self._free_ingest_result_store = self.free_upload_result
            self._free_ingest_error_store = self.free_upload_result.error
            return self.free_upload_result
        return await self.free_import(tracks=self.free_upload_tracks)

    def consume_free_ingest_feedback(self) -> tuple[SpotifyFreeIngestResult | None, str | None]:
        result = self._free_ingest_result_store
        error = self._free_ingest_error_store
        self._free_ingest_result_store = None
        self._free_ingest_error_store = None
        return result, error

    async def free_ingest_job_status(
        self, job_id: str | None
    ) -> SpotifyFreeIngestJobSnapshot | None:
        self.free_ingest_status_calls.append(job_id)
        return self.free_ingest_status_result


class _StubWatchlistService:
    def __init__(self, entries: Sequence[WatchlistRow] | None = None) -> None:
        self.entries = list(
            entries
            or (
                WatchlistRow(
                    artist_key="spotify:artist:stub",
                    priority=1,
                    state_key="watchlist.state.active",
                ),
            )
        )
        self.updated: list[tuple[str, int]] = []
        self.created: list[str] = []
        self.paused: list[str] = []
        self.pause_payloads: list[tuple[str | None, datetime | None]] = []
        self.resumed: list[str] = []
        self.deleted: list[str] = []
        self.pause_exception: Exception | None = None
        self.resume_exception: Exception | None = None
        self.delete_exception: Exception | None = None
        self.update_exception: Exception | None = None
        self.async_calls: list[str] = []
        self.sync_calls: list[str] = []

    def _make_table(self) -> WatchlistTable:
        return WatchlistTable(entries=tuple(self.entries))

    def list_entries(self, request) -> WatchlistTable:  # type: ignore[override]
        self.sync_calls.append("list")
        return self._make_table()

    async def list_entries_async(self, request) -> WatchlistTable:
        self.async_calls.append("list")
        await asyncio.sleep(0)
        return self._make_table()

    async def create_entry(
        self,
        request,
        *,
        artist_key: str,
        priority: int | None = None,
        pause_reason: str | None = None,
        resume_at: datetime | None = None,
    ) -> WatchlistTable:
        self.async_calls.append("create")
        await asyncio.sleep(0)
        row = WatchlistRow(
            artist_key=artist_key,
            priority=priority if priority is not None else 0,
            state_key="watchlist.state.active",
        )
        self.entries.insert(0, row)
        self.created.append(artist_key)
        if pause_reason is not None or resume_at is not None:
            return await self.pause_entry(
                request,
                artist_key=artist_key,
                reason=pause_reason,
                resume_at=resume_at,
            )
        return self._make_table()

    async def update_priority(
        self,
        request,
        *,
        artist_key: str,
        priority: int,
    ) -> WatchlistTable:
        self.async_calls.append("update")
        await asyncio.sleep(0)
        if self.update_exception:
            raise self.update_exception
        self.updated.append((artist_key, priority))
        row = WatchlistRow(
            artist_key=artist_key,
            priority=priority,
            state_key="watchlist.state.active",
        )
        self.entries = [row] + [entry for entry in self.entries if entry.artist_key != artist_key]
        return self._make_table()

    async def pause_entry(
        self,
        request,
        *,
        artist_key: str,
        reason: str | None = None,
        resume_at: datetime | None = None,
    ) -> WatchlistTable:
        self.async_calls.append("pause")
        await asyncio.sleep(0)
        self.pause_payloads.append((reason, resume_at))
        if self.pause_exception:
            raise self.pause_exception
        self.paused.append(artist_key)
        updated: list[WatchlistRow] = []
        for entry in self.entries:
            if entry.artist_key == artist_key:
                updated.append(
                    WatchlistRow(
                        artist_key=entry.artist_key,
                        priority=entry.priority,
                        state_key="watchlist.state.paused",
                        paused=True,
                    )
                )
            else:
                updated.append(entry)
        self.entries = updated
        return self._make_table()

    async def resume_entry(self, request, *, artist_key: str) -> WatchlistTable:
        self.async_calls.append("resume")
        await asyncio.sleep(0)
        if self.resume_exception:
            raise self.resume_exception
        self.resumed.append(artist_key)
        updated: list[WatchlistRow] = []
        for entry in self.entries:
            if entry.artist_key == artist_key:
                updated.append(
                    WatchlistRow(
                        artist_key=entry.artist_key,
                        priority=entry.priority,
                        state_key="watchlist.state.active",
                        paused=False,
                    )
                )
            else:
                updated.append(entry)
        self.entries = updated
        return self._make_table()

    async def delete_entry(self, request, *, artist_key: str) -> WatchlistTable:
        self.async_calls.append("delete")
        await asyncio.sleep(0)
        if self.delete_exception:
            raise self.delete_exception
        self.deleted.append(artist_key)
        self.entries = [entry for entry in self.entries if entry.artist_key != artist_key]
        return self._make_table()


class _StubSoulseekUiService:
    def __init__(self) -> None:
        self.connection = StatusResponse(status="connected")
        self.health = IntegrationHealth(
            overall="ok",
            providers=(
                ProviderHealth(
                    provider="soulseek",
                    status="ok",
                    details={"latency": "120ms"},
                ),
            ),
        )
        self.config = SoulseekConfig(
            base_url="http://localhost:5030",
            api_key="token",
            timeout_ms=8000,
            retry_max=3,
            retry_backoff_base_ms=250,
            retry_jitter_pct=20.0,
            preferred_formats=("flac", "mp3"),
            max_results=50,
        )
        self.security = SecurityConfig(
            profile="default",
            api_keys=("primary-key",),
            allowlist=(),
            allowed_origins=(),
            _require_auth_default=True,
            _rate_limiting_default=True,
            ui_cookies_secure=True,
        )
        self.status_exception: Exception | None = None
        self.health_exception: Exception | None = None
        self.config_exception: Exception | None = None
        self.upload_rows: list[SoulseekUploadRow] = [
            SoulseekUploadRow(
                identifier="upload-1",
                filename="example.flac",
                status="uploading",
                progress=0.25,
                size_bytes=1_048_576,
                speed_bps=2_048.0,
                username="tester",
            )
        ]
        self.upload_exception: Exception | None = None
        self.cancel_exception: Exception | None = None
        self.upload_calls: list[bool] = []
        self.cancelled: list[str] = []
        self._delegate_service: SoulseekUiService | None = None
        self.profile = SoulseekUserProfile(
            username="alice",
            address={"ip": "127.0.0.1", "port": "5030"},
            info={"shared": "42"},
        )
        self.profile_exception: Exception | None = None
        self.profile_calls: list[str] = []
        self.user_status_result = SoulseekUserStatus(
            username="alice",
            state="online",
            message="Ready to trade",
            shared_files=42,
            average_speed_bps=2048.0,
        )
        self.user_status_exception: Exception | None = None
        self.user_status_calls: list[str] = []
        self.user_browsing_status_result = SoulseekUserBrowsingStatus(
            username="alice",
            state="queued",
            progress=0.5,
            queue_position=2,
            queue_length=5,
            message="Awaiting slot",
        )
        self.user_browsing_status_exception: Exception | None = None
        self.user_browsing_status_calls: list[str] = []
        self.directory_listing = SoulseekUserDirectoryListing(
            username="alice",
            current_path="Music",
            parent_path=None,
            directories=(SoulseekUserDirectoryEntry(name="Albums", path="Music/Albums"),),
            files=(
                SoulseekUserFileEntry(
                    name="track.flac",
                    path="Music/track.flac",
                    size_bytes=1_048_576,
                ),
            ),
        )
        self.directory_exception: Exception | None = None
        self.directory_calls: list[tuple[str, str | None]] = []

    async def status(self) -> StatusResponse:
        if self.status_exception:
            raise self.status_exception
        return self.connection

    async def integration_health(self) -> IntegrationHealth:
        if self.health_exception:
            raise self.health_exception
        return self.health

    def soulseek_config(self) -> SoulseekConfig:
        if self.config_exception:
            raise self.config_exception
        return self.config

    def security_config(self) -> SecurityConfig:
        if self.config_exception:
            raise self.config_exception
        return self.security

    async def uploads(self, *, include_all: bool = False) -> Sequence[SoulseekUploadRow]:
        if self.upload_exception:
            raise self.upload_exception
        self.upload_calls.append(include_all)
        return tuple(self.upload_rows)

    async def cancel_upload(self, *, upload_id: str) -> None:
        if self.cancel_exception:
            raise self.cancel_exception
        self.cancelled.append(upload_id)

    async def user_profile(self, *, username: str) -> SoulseekUserProfile:
        if self.profile_exception:
            raise self.profile_exception
        self.profile_calls.append(username)
        return self.profile

    async def user_status(self, *, username: str) -> SoulseekUserStatus:
        self.user_status_calls.append(username)
        if self.user_status_exception:
            raise self.user_status_exception
        return self.user_status_result

    async def user_browsing_status(self, *, username: str) -> SoulseekUserBrowsingStatus:
        self.user_browsing_status_calls.append(username)
        if self.user_browsing_status_exception:
            raise self.user_browsing_status_exception
        return self.user_browsing_status_result

    async def user_directory(
        self,
        *,
        username: str,
        path: str | None = None,
    ) -> SoulseekUserDirectoryListing:
        if self.directory_exception:
            raise self.directory_exception
        self.directory_calls.append((username, path))
        return self.directory_listing

    def suggested_tasks(
        self,
        *,
        status: StatusResponse,
        health: IntegrationHealth,
        limit: int = 20,
    ):
        if self._delegate_service is None:

            class _DelegateRegistry:
                def initialise(self) -> None:
                    return None

            self._delegate_service = SoulseekUiService(
                request=SimpleNamespace(),
                config=SimpleNamespace(soulseek=self.config, security=self.security),
                soulseek_client=SimpleNamespace(),
                registry=_DelegateRegistry(),
            )
        return self._delegate_service.suggested_tasks(
            status=status,
            health=health,
            limit=limit,
        )


def test_soulseek_status_fragment_renders_badges(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/status",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "Daemon connectivity" in response.text
            assert "Integration health" in response.text
            assert 'data-test="soulseek-provider-soulseek"' in response.text
            assert "latency" in response.text
            assert 'id="primary-navigation"' in response.text
            assert 'data-test="nav-soulseek-status"' in response.text
            assert 'hx-swap-oob="outerHTML"' in response.text
            snippet_index = response.text.index('data-test="nav-soulseek-status"')
            snippet = response.text[max(0, snippet_index - 200) : snippet_index + 200]
            assert "status-badge--success" in snippet
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_page_reports_full_completion_when_connected(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "Completion: 100%" in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_status_fragment_handles_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.status_exception = RuntimeError("boom")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/status",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=500)
            assert "Unable to load Soulseek status." in response.text
            assert 'data-test="fragment-retry"' in response.text
            assert 'hx-get="http://testserver/ui/soulseek/status"' in response.text
            assert 'hx-target="#hx-soulseek-status"' in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_status_fragment_updates_navigation_badge_variant(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.connection = StatusResponse(status="failed")
    stub.health = IntegrationHealth(
        overall="down",
        providers=(ProviderHealth(provider="soulseek", status="down", details={}),),
    )
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/status",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert 'data-test="nav-soulseek-status"' in response.text
            snippet_index = response.text.index('data-test="nav-soulseek-status"')
            snippet = response.text[max(0, snippet_index - 200) : snippet_index + 200]
            assert "status-badge--danger" in snippet
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_config_fragment_renders_table(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/config",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "Soulseek configuration" in response.text
            assert 'data-test="soulseek-config-base-url"' in response.text
            assert "http://localhost:5030" in response.text
            assert 'data-test="soulseek-config-api-key"' in response.text
            snippet_index = response.text.index('data-test="soulseek-config-api-key"')
            snippet = response.text[max(0, snippet_index - 50) : snippet_index + 100]
            assert "••••••" in snippet
            assert "status-badge--danger" not in snippet
            assert "token" not in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_config_fragment_marks_missing_api_key(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.config = replace(stub.config, api_key=None)
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/config",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert 'data-test="soulseek-config-api-key"' in response.text
            snippet_index = response.text.index('data-test="soulseek-config-api-key"')
            snippet = response.text[max(0, snippet_index - 50) : snippet_index + 150]
            assert "Missing" in snippet
            assert "status-badge--danger" in snippet
            assert "••••••" not in snippet
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_config_fragment_handles_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.config_exception = RuntimeError("fail")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/config",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=500)
            assert "Unable to load Soulseek configuration." in response.text
            assert 'data-test="fragment-retry"' in response.text
            assert 'hx-get="http://testserver/ui/soulseek/config"' in response.text
            assert 'hx-target="#hx-soulseek-configuration"' in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_uploads_fragment_success(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.upload_rows = [
        SoulseekUploadRow(
            identifier="abc-123",
            filename="track.flac",
            status="uploading",
            progress=0.5,
            size_bytes=5_242_880,
            speed_bps=8_192.0,
            username="dj",
        )
    ]
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/uploads",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            body = response.text
            assert "track.flac" in body
            assert "50%" in body
            assert "MiB" in body
            assert "Cancel upload" in body
            assert "hx-soulseek-uploads" in body
            assert "Remove completed uploads" in body
            assert 'hx-post="/ui/soulseek/uploads/cleanup"' in body
            _assert_button_enabled(body, "soulseek-upload-cancel")
            _assert_button_enabled(body, "soulseek-uploads-cleanup")
            assert stub.upload_calls == [False]
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_uploads_fragment_handles_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.upload_exception = HTTPException(status_code=502, detail="boom")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/uploads",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=502)
            assert "boom" in response.text
            assert 'data-test="fragment-retry"' in response.text
            assert 'hx-get="http://testserver/ui/soulseek/uploads"' in response.text
            assert 'hx-target="#hx-soulseek-uploads"' in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_uploads_fragment_operator_disables_actions(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.upload_rows = [
        SoulseekUploadRow(
            identifier="abc-123",
            filename="track.flac",
            status="uploading",
            progress=0.5,
            size_bytes=5_242_880,
            speed_bps=8_192.0,
            username="dj",
        )
    ]
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/uploads",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            body = response.text
            _assert_button_disabled(body, "soulseek-upload-cancel")
            _assert_button_disabled(body, "soulseek-uploads-cleanup")
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_uploads_fragment_requires_feature(monkeypatch) -> None:
    extra_env = {"UI_FEATURE_SOULSEEK": "false"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        response = client.get(
            "/ui/soulseek/uploads",
            headers={"Cookie": _cookies_header(client)},
        )
        assert response.status_code == 404
        assert response.headers.get("content-type", "").startswith("application/json")


def test_soulseek_upload_cancel_success(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.upload_rows = []
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/uploads/cancel",
                data={"upload_id": "upload-1"},
                headers=headers,
            )
            _assert_html_response(response)
            assert "No uploads are currently in progress." in response.text
            assert stub.cancelled == ["upload-1"]
            assert stub.upload_calls == [False]
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_info_fragment_success(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/info",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            body = response.text
            assert "Lookup user" in body
            assert "127.0.0.1" in body
            assert "5030" in body
            assert "User status" in body
            assert "Online" in body
            assert "Browse progress: 50%" in body
            assert "track.flac" not in body
            assert stub.profile_calls == ["alice"]
            assert stub.user_status_calls == ["alice"]
            assert stub.user_browsing_status_calls == ["alice"]
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_info_fragment_displays_zero_values(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.user_status_result = SoulseekUserStatus(
        username="alice",
        state="online",
        message=None,
        shared_files=0,
        average_speed_bps=0.0,
    )
    stub.user_browsing_status_result = SoulseekUserBrowsingStatus(
        username="alice",
        state="queued",
        progress=0.0,
        queue_position=0,
        queue_length=0,
        message=None,
    )
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/info",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            body = response.text
            assert 'data-test="soulseek-user-status-shared"' in body
            assert "0 shared files reported." in body
            assert 'data-test="soulseek-user-browse-progress"' in body
            assert "Browse progress: 0%" in body
            assert 'data-test="soulseek-user-browse-queue"' in body
            assert "Queue position 0" in body
            assert "Queue position 0 of" not in body
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_info_fragment_handles_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.profile_exception = HTTPException(status_code=502, detail="profile error")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/info",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=502)
            assert "profile error" in response.text
            assert 'hx-target="#hx-soulseek-user-info"' in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_info_fragment_handles_unexpected_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.profile_exception = RuntimeError("boom")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/info",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=500)
            assert "Unable to load Soulseek user profile." in response.text
            assert 'hx-target="#hx-soulseek-user-info"' in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_info_fragment_status_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.user_status_exception = HTTPException(status_code=504, detail="status error")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/info",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=504)
            assert "status error" in response.text
            assert 'hx-target="#hx-soulseek-user-info"' in response.text
            assert stub.profile_calls == ["alice"]
            assert stub.user_status_calls == ["alice"]
            assert stub.user_browsing_status_calls == []
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_info_fragment_browsing_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.user_browsing_status_exception = HTTPException(status_code=429, detail="browse error")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/info",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=429)
            assert "browse error" in response.text
            assert 'hx-target="#hx-soulseek-user-info"' in response.text
            assert stub.profile_calls == ["alice"]
            assert stub.user_status_calls == ["alice"]
            assert stub.user_browsing_status_calls == ["alice"]
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_directory_fragment_success(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/directory",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            body = response.text
            assert "Browse directory" in body
            assert "Albums" in body
            assert "track.flac" in body
            assert stub.directory_calls == [("alice", None)]
            assert stub.user_status_calls == ["alice"]
            assert stub.user_browsing_status_calls == ["alice"]
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_directory_fragment_handles_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.directory_exception = HTTPException(status_code=503, detail="dir error")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/directory",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=503)
            assert "dir error" in response.text
            assert 'hx-target="#hx-soulseek-user-directory"' in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_directory_fragment_handles_unexpected_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.directory_exception = RuntimeError("boom")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/directory",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=500)
            assert "Unable to load Soulseek user directory." in response.text
            assert 'hx-target="#hx-soulseek-user-directory"' in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_directory_fragment_status_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.user_status_exception = HTTPException(status_code=410, detail="status fail")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/directory",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=410)
            assert "status fail" in response.text
            assert 'hx-target="#hx-soulseek-user-directory"' in response.text
            assert stub.user_status_calls == ["alice"]
            assert stub.user_browsing_status_calls == []
            assert stub.directory_calls == []
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_user_directory_fragment_browsing_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.user_browsing_status_exception = HTTPException(status_code=425, detail="browse fail")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/user/directory",
                params={"username": "alice"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=425)
            assert "browse fail" in response.text
            assert 'hx-target="#hx-soulseek-user-directory"' in response.text
            assert stub.user_status_calls == ["alice"]
            assert stub.user_browsing_status_calls == ["alice"]
            assert stub.directory_calls == []
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_uploads_cleanup_success(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.upload_rows = []
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    client_instance = object()
    app.dependency_overrides[get_soulseek_client] = lambda: client_instance
    calls: list[object] = []

    async def _fake_cleanup(*, client: object) -> None:  # type: ignore[override]
        calls.append(client)

    monkeypatch.setattr("app.ui.routes.soulseek.soulseek_remove_completed_uploads", _fake_cleanup)

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/uploads/cleanup",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "scope": "all",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert "No uploads are currently in progress." in response.text
            assert calls == [client_instance]
            assert stub.upload_calls == [True]
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_uploads_cleanup_failure(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    app.dependency_overrides[get_soulseek_client] = lambda: object()

    async def _fail_cleanup(*, client: object) -> None:  # type: ignore[override]
        raise HTTPException(status_code=503, detail="unavailable")

    monkeypatch.setattr("app.ui.routes.soulseek.soulseek_remove_completed_uploads", _fail_cleanup)

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/uploads/cleanup",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response, status_code=503)
            assert "unavailable" in response.text
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_downloads_fragment_success(monkeypatch) -> None:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=42,
                filename="retry.flac",
                status="failed",
                progress=0.5,
                priority=3,
                username="dj",
                created_at=None,
                updated_at=None,
                retry_count=2,
                next_retry_at=datetime(2024, 1, 1, 12, 0, 0),
                last_error="network timeout",
                live_queue={"status": "waiting", "eta": "30s"},
                lyrics_status="done",
                has_lyrics=True,
                lyrics_path="/downloads/retry.lrc",
                artwork_status="done",
                has_artwork=True,
                artwork_path="/downloads/retry.jpg",
                organized_path="/library/retry.flac",
                spotify_track_id="track-42",
                spotify_album_id="album-42",
            )
        ],
        limit=20,
        offset=0,
        has_next=True,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/soulseek/downloads", headers=headers)
            _assert_html_response(response)
            html = response.text
            assert "retry.flac" in html
            assert "Retries" in html
            assert "network timeout" in html
            assert "status=waiting" in html
            assert "eta=30s" in html
            assert "Active downloads" in html
            assert "hx-soulseek-downloads" in html
            assert 'data-scope="active"' in html
            assert 'hx-get="/ui/soulseek/downloads?limit=20&offset=20"' in html
            assert 'hx-push-url="/ui/soulseek/downloads?limit=20&offset=20"' in html
            assert "Remove completed downloads" in html
            assert 'hx-delete="/ui/soulseek/downloads/cleanup"' in html
            assert 'data-modal-target="#modal-root"' in html
            assert 'data-action-target="#hx-soulseek-downloads"' in html

            def _attr_value(name: str) -> str:
                match = re.search(rf'data-{name}="([^"]+)"', html)
                assert match is not None, name
                return match.group(1)

            assert "soulseek/download" in _attr_value("lyrics-view-base")
            assert "soulseek/download" in _attr_value("lyrics-refresh-base")
            assert "soulseek/download" in _attr_value("metadata-view-base")
            assert "soulseek/download" in _attr_value("metadata-refresh-base")
            assert "soulseek/download" in _attr_value("artwork-view-base")
            assert "soulseek/download" in _attr_value("artwork-refresh-base")
            _assert_button_enabled(html, "soulseek-download-requeue")
            _assert_button_enabled(html, "soulseek-download-cancel")
            _assert_button_enabled(html, "soulseek-downloads-cleanup")
            _assert_button_enabled(html, "soulseek-download-lyrics-view-42")
            _assert_button_enabled(html, "soulseek-download-lyrics-refresh-42")
            _assert_button_enabled(html, "soulseek-download-metadata-view-42")
            _assert_button_enabled(html, "soulseek-download-metadata-refresh-42")
            _assert_button_enabled(html, "soulseek-download-artwork-view-42")
            _assert_button_enabled(html, "soulseek-download-artwork-refresh-42")
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_soulseek_downloads_fragment_operator_disables_actions(monkeypatch) -> None:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=7,
                filename="queue.flac",
                status="failed",
                progress=0.0,
                priority=1,
                username=None,
                created_at=None,
                updated_at=None,
                lyrics_status="pending",
                has_lyrics=False,
                artwork_status="pending",
                has_artwork=False,
            )
        ],
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/soulseek/downloads", headers=headers)
            _assert_html_response(response)
            html = response.text
            _assert_button_disabled(html, "soulseek-download-requeue")
            _assert_button_disabled(html, "soulseek-download-cancel")
            _assert_button_disabled(html, "soulseek-downloads-cleanup")
            _assert_button_disabled(html, "soulseek-download-lyrics-view-7")
            _assert_button_disabled(html, "soulseek-download-lyrics-refresh-7")
            _assert_button_disabled(html, "soulseek-download-metadata-view-7")
            _assert_button_disabled(html, "soulseek-download-metadata-refresh-7")
            _assert_button_disabled(html, "soulseek-download-artwork-view-7")
            _assert_button_disabled(html, "soulseek-download-artwork-refresh-7")
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_soulseek_downloads_fragment_handles_error(monkeypatch) -> None:
    page = DownloadPage(items=[], limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    stub.list_exception = AppError(code=ErrorCode.INTERNAL_ERROR, message="fail", http_status=502)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/soulseek/downloads", headers=headers)
            _assert_html_response(response, status_code=502)
            assert "fail" in response.text
            assert 'data-test="fragment-retry"' in response.text
            assert 'hx-get="http://testserver/ui/soulseek/downloads"' in response.text
            assert 'hx-target="#hx-soulseek-downloads"' in response.text
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_soulseek_downloads_fragment_pagination_links(monkeypatch) -> None:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=84,
                filename="mix.flac",
                status="completed",
                progress=1.0,
                priority=1,
                username="dj",
                created_at=None,
                updated_at=None,
                retry_count=0,
                next_retry_at=None,
                last_error=None,
                live_queue=None,
            )
        ],
        limit=20,
        offset=10,
        has_next=True,
        has_previous=True,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/soulseek/downloads", headers=headers)
            _assert_html_response(response)
            html = response.text
            assert 'hx-get="/ui/soulseek/downloads?limit=20&offset=0"' in html
            assert 'hx-push-url="/ui/soulseek/downloads?limit=20&offset=0"' in html
            assert 'hx-get="/ui/soulseek/downloads?limit=20&offset=30"' in html
            assert 'hx-push-url="/ui/soulseek/downloads?limit=20&offset=30"' in html
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_soulseek_downloads_fragment_all_scope(monkeypatch) -> None:
    page = DownloadPage(items=[], limit=50, offset=0, has_next=True, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get(
                "/ui/soulseek/downloads",
                params={"all": "1", "limit": "50"},
                headers=headers,
            )
            _assert_html_response(response)
            html = response.text
            assert "All downloads" in html
            assert 'data-scope="all"' in html
            assert "No Soulseek downloads" in html
            assert 'hx-get="/ui/soulseek/downloads?limit=50&offset=50&all=1"' in html
            assert 'hx-push-url="/ui/soulseek/downloads?limit=50&offset=50&all=1"' in html
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_soulseek_discography_jobs_fragment_success(monkeypatch) -> None:
    jobs = [_make_discography_job(7, artist_name="Artist Seven", artist_id="soulseek:artist-7")]

    def _fake_load(limit: int = 25) -> list[Any]:  # pragma: no cover - signature compatibility
        return jobs

    monkeypatch.setattr("app.ui.routes.soulseek._load_discography_jobs", _fake_load)

    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/soulseek/discography/jobs", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert 'data-test="soulseek-discography-open-modal"' in html
        assert 'hx-target="#modal-root"' in html
        assert "/ui/soulseek/discography/jobs/modal" in html
        assert 'id="hx-soulseek-discography-jobs"' in html
        assert 'data-count="1"' in html
        assert 'data-test="soulseek-discography-job-7"' in html
        assert 'data-test="soulseek-discography-job-7-status"' in html
        assert "Artist Seven (soulseek:artist-7)" in html


def test_soulseek_discography_jobs_fragment_failure(monkeypatch) -> None:
    def _raise_load(limit: int = 25) -> list[Any]:  # pragma: no cover - signature compatibility
        raise RuntimeError("database offline")

    monkeypatch.setattr("app.ui.routes.soulseek._load_discography_jobs", _raise_load)

    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/soulseek/discography/jobs", headers=headers)
        _assert_html_response(response, status_code=500)
        html = response.text
        assert "Unable to load discography jobs." in html
        assert 'data-test="fragment-retry"' in html
        assert 'hx-target="#hx-soulseek-discography-jobs"' in html


def test_soulseek_discography_jobs_fragment_feature_disabled(monkeypatch) -> None:
    extra_env = {"UI_FEATURE_SOULSEEK": "false"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/soulseek/discography/jobs", headers=headers)
        _assert_json_error(response, status_code=404)


def test_soulseek_discography_job_modal_success(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.get("/ui/soulseek/discography/jobs/modal", headers=headers)
        _assert_html_response(response)
        html = response.text
        token = headers["X-CSRF-Token"]
        assert 'data-test="soulseek-discography-modal"' in html
        assert 'hx-target="#hx-soulseek-discography-jobs"' in html
        assert "/ui/soulseek/discography/jobs" in html
        assert f'value="{token}"' in html
        assert 'data-test="soulseek-discography-artist-id"' in html
        assert 'data-test="soulseek-discography-artist-name"' in html


def test_soulseek_discography_job_modal_feature_disabled(monkeypatch) -> None:
    extra_env = {"UI_FEATURE_SOULSEEK": "false"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/soulseek/discography/jobs/modal", headers=headers)
        _assert_json_error(response, status_code=404)


def test_soulseek_discography_jobs_submit_success(monkeypatch) -> None:
    jobs = [_make_discography_job(11, artist_name="Artist Eleven", artist_id="soulseek:artist-11")]

    def _fake_load(limit: int = 25) -> list[Any]:  # pragma: no cover - signature compatibility
        return jobs

    monkeypatch.setattr("app.ui.routes.soulseek._load_discography_jobs", _fake_load)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(object())
    )
    calls: list[Any] = []

    async def _fake_download(*, payload: Any, request: Any, session: Any) -> Any:  # type: ignore[override]
        calls.append(payload)
        return SimpleNamespace(job_id="job-11", status="queued")

    monkeypatch.setattr(
        "app.ui.routes.soulseek.soulseek_discography_download",
        _fake_download,
        raising=False,
    )

    with _create_client(monkeypatch) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(
            "/ui/soulseek/discography/jobs",
            data={
                "csrftoken": headers["X-CSRF-Token"],
                "artist_id": "soulseek:artist-11",
                "artist_name": "Artist Eleven",
            },
            headers=headers,
        )
        _assert_html_response(response)
        html = response.text
        assert calls and calls[0].artist_id == "soulseek:artist-11"
        assert calls[0].artist_name == "Artist Eleven"
        assert "Queued discography download for Artist Eleven." in html
        assert 'id="hx-soulseek-discography-jobs"' in html
        assert 'data-count="1"' in html
        assert 'data-test="soulseek-discography-job-11-status"' in html
        assert "Artist Eleven (soulseek:artist-11)" in html


def test_soulseek_discography_jobs_submit_validation_error(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(
            "/ui/soulseek/discography/jobs",
            data={
                "csrftoken": headers["X-CSRF-Token"],
                "artist_id": " ",
                "artist_name": "Ignored",
            },
            headers=headers,
        )
        _assert_html_response(response, status_code=400)
        assert response.headers["HX-Retarget"] == "#modal-root"
        assert response.headers["HX-Reswap"] == "innerHTML"
        html = response.text
        assert 'data-test="soulseek-discography-artist-id-error"' in html
        assert "An artist ID is required." in html
        assert 'hx-target="#hx-soulseek-discography-jobs"' in html
        assert "/ui/soulseek/discography/jobs" in html


def test_soulseek_discography_jobs_submit_http_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(object())
    )

    async def _raise_download(*, payload: Any, request: Any, session: Any) -> Any:  # type: ignore[override]
        raise HTTPException(status_code=503, detail="discography worker offline")

    monkeypatch.setattr(
        "app.ui.routes.soulseek.soulseek_discography_download",
        _raise_download,
        raising=False,
    )

    with _create_client(monkeypatch) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(
            "/ui/soulseek/discography/jobs",
            data={
                "csrftoken": headers["X-CSRF-Token"],
                "artist_id": "soulseek:artist-1",
                "artist_name": "Artist One",
            },
            headers=headers,
        )
        _assert_html_response(response, status_code=503)
        assert response.headers["HX-Retarget"] == "#modal-root"
        assert response.headers["HX-Reswap"] == "innerHTML"
        html = response.text
        assert 'data-test="soulseek-discography-artist-id-error"' in html
        assert "discography worker offline" in html


def test_soulseek_discography_jobs_submit_unexpected_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(object())
    )

    async def _boom(*, payload: Any, request: Any, session: Any) -> Any:  # type: ignore[override]
        raise RuntimeError("crash")

    monkeypatch.setattr(
        "app.ui.routes.soulseek.soulseek_discography_download",
        _boom,
        raising=False,
    )

    with _create_client(monkeypatch) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(
            "/ui/soulseek/discography/jobs",
            data={
                "csrftoken": headers["X-CSRF-Token"],
                "artist_id": "soulseek:artist-2",
                "artist_name": "Artist Two",
            },
            headers=headers,
        )
        _assert_html_response(response, status_code=500)
        assert response.headers["HX-Retarget"] == "#modal-root"
        assert response.headers["HX-Reswap"] == "innerHTML"
        html = response.text
        assert 'data-test="soulseek-discography-artist-id-error"' in html
        assert "Unable to queue the discography job." in html


def test_soulseek_discography_jobs_submit_missing_csrf_token(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.post(
            "/ui/soulseek/discography/jobs",
            data={"artist_id": "soulseek:artist-3", "artist_name": "Artist Three"},
            headers=headers,
        )
        _assert_json_error(response, status_code=403)
        payload = response.json()
        assert payload.get("error", {}).get("message") == "Missing CSRF token."


def test_soulseek_discography_jobs_submit_feature_disabled(monkeypatch) -> None:
    extra_env = {"UI_FEATURE_SOULSEEK": "false"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(
            "/ui/soulseek/discography/jobs",
            data={
                "csrftoken": headers["X-CSRF-Token"],
                "artist_id": "soulseek:artist-4",
                "artist_name": "Artist Four",
            },
            headers=headers,
        )
        _assert_json_error(response, status_code=404)
        payload = response.json()
        assert payload.get("error", {}).get("message") == "The requested UI feature is disabled."


def test_soulseek_download_lyrics_modal_renders_modal(monkeypatch) -> None:
    download = type(
        "Download",
        (),
        {
            "id": 42,
            "filename": "lyrics.flac",
            "lyrics_status": "done",
            "has_lyrics": True,
        },
    )()
    stub_session = _StubDbSession(download)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(stub_session)
    )
    monkeypatch.setattr(
        "app.ui.routes.soulseek.api_soulseek_download_lyrics",
        lambda **_: PlainTextResponse("Line 1\nLine 2"),
    )

    with _create_client(monkeypatch) as client:
        _login(client)
        response = client.get(
            "/ui/soulseek/download/42/lyrics",
            headers={"Cookie": _cookies_header(client)},
        )
        _assert_html_response(response)
        html = response.text
        assert "soulseek-download-lyrics-modal" in html
        assert "Line 1" in html
        assert "Lyrics ready" in html


def test_soulseek_download_lyrics_modal_pending(monkeypatch) -> None:
    download = type(
        "Download",
        (),
        {
            "id": 8,
            "filename": "pending.flac",
            "lyrics_status": "pending",
            "has_lyrics": False,
        },
    )()
    stub_session = _StubDbSession(download)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(stub_session)
    )
    monkeypatch.setattr(
        "app.ui.routes.soulseek.api_soulseek_download_lyrics",
        lambda **_: JSONResponse({"status": "pending"}, status_code=202),
    )

    with _create_client(monkeypatch) as client:
        _login(client)
        response = client.get(
            "/ui/soulseek/download/8/lyrics",
            headers={"Cookie": _cookies_header(client)},
        )
        _assert_html_response(response)
        html = response.text
        assert "Lyrics generation is still in progress" in html


def test_soulseek_download_metadata_modal_renders_modal(monkeypatch) -> None:
    download = type("Download", (), {"id": 51, "filename": "meta.flac"})()
    stub_session = _StubDbSession(download)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(stub_session)
    )
    metadata = type(
        "Metadata",
        (),
        {
            "filename": "meta.flac",
            "genre": "Rock",
            "composer": "Composer",
            "producer": "Producer",
            "isrc": "ISRC123",
            "copyright": "2024",
        },
    )()
    monkeypatch.setattr(
        "app.ui.routes.soulseek.api_soulseek_download_metadata", lambda **_: metadata
    )

    with _create_client(monkeypatch) as client:
        _login(client)
        response = client.get(
            "/ui/soulseek/download/51/metadata",
            headers={"Cookie": _cookies_header(client)},
        )
        _assert_html_response(response)
        html = response.text
        assert "soulseek-download-metadata-modal" in html
        assert "Rock" in html
        assert "Composer" in html


def test_soulseek_download_metadata_modal_handles_error(monkeypatch) -> None:
    download = type("Download", (), {"id": 77, "filename": "error.flac"})()
    stub_session = _StubDbSession(download)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(stub_session)
    )

    def _raise_metadata(**_: object) -> None:
        raise HTTPException(status_code=500, detail="metadata failure")

    monkeypatch.setattr("app.ui.routes.soulseek.api_soulseek_download_metadata", _raise_metadata)

    with _create_client(monkeypatch) as client:
        _login(client)
        response = client.get(
            "/ui/soulseek/download/77/metadata",
            headers={"Cookie": _cookies_header(client)},
        )
        _assert_html_response(response, status_code=500)
        assert "metadata failure" in response.text


def test_soulseek_download_artwork_modal_renders_modal(monkeypatch) -> None:
    download = type(
        "Download",
        (),
        {
            "id": 33,
            "filename": "cover.flac",
            "artwork_status": "ready",
            "has_artwork": True,
        },
    )()
    stub_session = _StubDbSession(download)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(stub_session)
    )

    async def _noop_artwork(**_: object) -> None:
        return None

    monkeypatch.setattr("app.ui.routes.soulseek.api_soulseek_download_artwork", _noop_artwork)

    with _create_client(monkeypatch) as client:
        _login(client)
        response = client.get(
            "/ui/soulseek/download/33/artwork",
            headers={"Cookie": _cookies_header(client)},
        )
        _assert_html_response(response)
        html = response.text
        assert "soulseek-download-artwork-modal" in html
        assert "cover.flac" in html
        assert "soulseek-download-artwork-image" in html


def test_soulseek_download_artwork_modal_handles_error(monkeypatch) -> None:
    download = type(
        "Download",
        (),
        {
            "id": 9,
            "filename": "art.flac",
            "artwork_status": "failed",
            "has_artwork": False,
        },
    )()
    stub_session = _StubDbSession(download)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(stub_session)
    )

    def _raise_artwork(**_: object) -> None:
        raise HTTPException(status_code=404, detail="missing artwork")

    monkeypatch.setattr("app.ui.routes.soulseek.api_soulseek_download_artwork", _raise_artwork)

    with _create_client(monkeypatch) as client:
        _login(client)
        response = client.get(
            "/ui/soulseek/download/9/artwork",
            headers={"Cookie": _cookies_header(client)},
        )
        _assert_html_response(response, status_code=404)
        assert "missing artwork" in response.text


def test_soulseek_download_requeue_success(monkeypatch) -> None:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=7,
                filename="queue.flac",
                status="failed",
                progress=0.0,
                priority=1,
                username=None,
                created_at=None,
                updated_at=None,
            )
        ],
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    calls: list[int] = []

    async def _fake_requeue(*, download_id: int, request: Any, session: Any) -> None:  # type: ignore[override]
        calls.append(download_id)

    monkeypatch.setattr("app.ui.routes.soulseek.soulseek_requeue_download", _fake_requeue)

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/downloads/7/requeue",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "scope": "all",
                    "limit": "20",
                    "offset": "0",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert calls == [7]
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_soulseek_download_requeue_failure(monkeypatch) -> None:
    page = DownloadPage(items=[], limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub

    async def _fail_requeue(*, download_id: int, request: Any, session: Any) -> None:  # type: ignore[override]
        raise HTTPException(status_code=409, detail="conflict")

    monkeypatch.setattr("app.ui.routes.soulseek.soulseek_requeue_download", _fail_requeue)

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/downloads/9/requeue",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "scope": "active",
                },
                headers=headers,
            )
            _assert_html_response(response, status_code=409)
            assert "conflict" in response.text
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_soulseek_download_cancel_success(monkeypatch) -> None:
    page = DownloadPage(items=[], limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    app.dependency_overrides[get_soulseek_client] = lambda: object()
    calls: list[int] = []

    async def _fake_cancel(*, download_id: int, session: Any, client: Any) -> None:  # type: ignore[override]
        calls.append(download_id)

    monkeypatch.setattr("app.ui.routes.soulseek.soulseek_cancel", _fake_cancel)

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/download/5",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "scope": "active",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert calls == [5]
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_download_cancel_failure(monkeypatch) -> None:
    page = DownloadPage(items=[], limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    app.dependency_overrides[get_soulseek_client] = lambda: object()

    async def _fail_cancel(*, download_id: int, session: Any, client: Any) -> None:  # type: ignore[override]
        raise HTTPException(status_code=404, detail="missing")

    monkeypatch.setattr("app.ui.routes.soulseek.soulseek_cancel", _fail_cancel)

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/download/99",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "scope": "active",
                },
                headers=headers,
            )
            _assert_html_response(response, status_code=404)
            assert "missing" in response.text
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_download_lyrics_refresh_success(monkeypatch) -> None:
    page = DownloadPage(items=(), limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    app.dependency_overrides[get_soulseek_client] = lambda: object()
    calls: list[int] = []

    async def _refresh(**_: object) -> None:
        calls.append(11)

    monkeypatch.setattr("app.ui.routes.soulseek.api_refresh_download_lyrics", _refresh)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(object())
    )

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/download/11/lyrics/refresh",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "scope": "active",
                    "limit": "20",
                    "offset": "0",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert calls == [11]
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_download_metadata_refresh_success(monkeypatch) -> None:
    page = DownloadPage(
        items=(
            DownloadRow(
                identifier=21,
                filename="meta.flac",
                status="completed",
                progress=1.0,
                priority=1,
                username="dj",
                created_at=None,
                updated_at=None,
                organized_path="/library/meta.flac",
                lyrics_status="done",
                has_lyrics=True,
                lyrics_path="/lyrics/meta.lrc",
                artwork_status="done",
                has_artwork=True,
                artwork_path="/artwork/meta.jpg",
            ),
        ),
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    app.dependency_overrides[get_soulseek_client] = lambda: object()
    calls: list[int] = []

    async def _refresh_metadata(**_: object) -> None:
        calls.append(21)

    monkeypatch.setattr("app.ui.routes.soulseek.api_refresh_download_metadata", _refresh_metadata)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(object())
    )

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/download/21/metadata/refresh",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "scope": "all",
                    "limit": "20",
                    "offset": "0",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert calls == [21]
            assert "soulseek-download-metadata-actions-21" in response.text
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_download_metadata_refresh_failure(monkeypatch) -> None:
    page = DownloadPage(items=(), limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    app.dependency_overrides[get_soulseek_client] = lambda: object()

    async def _refresh_metadata_fail(**_: object) -> None:
        raise HTTPException(status_code=503, detail="metadata refresh failed")

    monkeypatch.setattr(
        "app.ui.routes.soulseek.api_refresh_download_metadata", _refresh_metadata_fail
    )
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(object())
    )

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/download/22/metadata/refresh",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "scope": "active",
                },
                headers=headers,
            )
            _assert_html_response(response, status_code=503)
            assert "metadata refresh failed" in response.text
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_download_artwork_refresh_success(monkeypatch) -> None:
    page = DownloadPage(
        items=(
            DownloadRow(
                identifier=17,
                filename="art.flac",
                status="completed",
                progress=1.0,
                priority=1,
                username="dj",
                created_at=None,
                updated_at=None,
                organized_path="/library/art.flac",
                lyrics_status="done",
                has_lyrics=True,
                lyrics_path="/lyrics/art.lrc",
                artwork_status="done",
                has_artwork=True,
                artwork_path="/artwork/art.jpg",
            ),
        ),
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    app.dependency_overrides[get_soulseek_client] = lambda: object()
    calls: list[int] = []

    async def _refresh_artwork(**_: object) -> None:
        calls.append(17)

    monkeypatch.setattr("app.ui.routes.soulseek.api_soulseek_refresh_artwork", _refresh_artwork)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(object())
    )

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/download/17/artwork/refresh",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "scope": "all",
                    "limit": "20",
                    "offset": "0",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert calls == [17]
            assert "soulseek-download-artwork-actions-17" in response.text
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_download_artwork_refresh_failure(monkeypatch) -> None:
    page = DownloadPage(items=(), limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    app.dependency_overrides[get_soulseek_client] = lambda: object()

    async def _refresh_fail(**_: object) -> None:
        raise HTTPException(status_code=502, detail="artwork refresh failed")

    monkeypatch.setattr("app.ui.routes.soulseek.api_soulseek_refresh_artwork", _refresh_fail)
    monkeypatch.setattr(
        "app.ui.routes.soulseek.session_scope", lambda: _StubSessionContext(object())
    )

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/soulseek/download/13/artwork/refresh",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response, status_code=502)
            assert "artwork refresh failed" in response.text
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_downloads_cleanup_success(monkeypatch) -> None:
    page = DownloadPage(items=(), limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    client_instance = object()
    app.dependency_overrides[get_soulseek_client] = lambda: client_instance
    calls: list[object] = []

    async def _fake_cleanup(*, client: object) -> None:  # type: ignore[override]
        calls.append(client)

    monkeypatch.setattr("app.ui.routes.soulseek.soulseek_remove_completed_downloads", _fake_cleanup)

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.request(
                "DELETE",
                "/ui/soulseek/downloads/cleanup",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "limit": "20",
                    "offset": "0",
                    "scope": "active",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert "downloads" in response.text.lower()
            assert calls == [client_instance]
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


def test_soulseek_downloads_cleanup_failure(monkeypatch) -> None:
    page = DownloadPage(items=(), limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    app.dependency_overrides[get_soulseek_client] = lambda: object()

    async def _fail_cleanup(*, client: object) -> None:  # type: ignore[override]
        raise HTTPException(status_code=502, detail="cleanup failed")

    monkeypatch.setattr("app.ui.routes.soulseek.soulseek_remove_completed_downloads", _fail_cleanup)

    try:
        with _create_client(monkeypatch, extra_env=_admin_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.request(
                "DELETE",
                "/ui/soulseek/downloads/cleanup",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response, status_code=502)
            assert "cleanup failed" in response.text
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)
        app.dependency_overrides.pop(get_soulseek_client, None)


@pytest.mark.parametrize("role_name", ["operator", "read_only"])
@pytest.mark.parametrize(
    ("method", "url", "payload"),
    [
        ("post", "/ui/soulseek/downloads/7/requeue", {"scope": "all", "csrftoken": ""}),
        ("post", "/ui/soulseek/download/7", {"scope": "active", "csrftoken": ""}),
        ("delete", "/ui/soulseek/downloads/cleanup", {"csrftoken": "", "scope": "active"}),
        ("post", "/ui/soulseek/uploads/cancel", {"upload_id": "upload-1", "csrftoken": ""}),
        ("post", "/ui/soulseek/uploads/cleanup", {"csrftoken": "", "scope": "active"}),
    ],
)
def test_soulseek_admin_actions_forbidden(
    monkeypatch, role_name: str, method: str, url: str, payload: dict[str, str]
) -> None:
    overrides: list[Any] = []
    if "/ui/soulseek/download" in url:
        page = DownloadPage(items=(), limit=20, offset=0, has_next=False, has_previous=False)
        app.dependency_overrides[get_downloads_ui_service] = lambda: _RecordingDownloadsService(
            page
        )
        overrides.append(get_downloads_ui_service)
        app.dependency_overrides[get_soulseek_client] = lambda: object()
        overrides.append(get_soulseek_client)
    if "/ui/soulseek/uploads" in url:
        stub = _StubSoulseekUiService()
        app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
        overrides.append(get_soulseek_ui_service)
        app.dependency_overrides[get_soulseek_client] = lambda: object()
        overrides.append(get_soulseek_client)

    extra_env = None
    if role_name == "read_only":
        extra_env = _read_only_env()

    try:
        with _create_client(monkeypatch, extra_env=extra_env) as client:
            _login(client)
            headers = _csrf_headers(client)
            data = dict(payload)
            if "csrftoken" in data:
                data["csrftoken"] = headers["X-CSRF-Token"]
            response = client.request(method.upper(), url, data=data, headers=headers)
            assert response.status_code == 403
    finally:
        for override in overrides:
            app.dependency_overrides.pop(override, None)


def test_activity_fragment_requires_session(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        response = client.get("/ui/activity/table")
        assert response.status_code == 401


def test_activity_fragment_renders_table(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        activity_manager.record(action_type="test", status="ok")
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/activity/table", headers=headers)
        _assert_html_response(response)
        body = response.text
        assert "<table" in body
        assert "data-total" in body


def test_activity_fragment_app_error(monkeypatch) -> None:
    stub = _StubActivityService()
    stub.exception = AppError(
        "activity unavailable",
        code=ErrorCode.DEPENDENCY_ERROR,
        http_status=502,
    )
    app.dependency_overrides[get_activity_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/activity/table", headers=headers)
            _assert_html_response(response, status_code=502)
            assert "activity unavailable" in response.text
    finally:
        app.dependency_overrides.pop(get_activity_ui_service, None)


def test_watchlist_fragment_enforces_role(monkeypatch) -> None:
    fingerprint = fingerprint_api_key("primary-key")
    extra_env = {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/watchlist/table", headers=headers)
        _assert_json_error(response, status_code=403)


def test_downloads_fragment_forbidden_for_read_only(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env=_read_only_env()) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/downloads/table", headers=headers)
        _assert_json_error(response, status_code=403)


def test_jobs_fragment_forbidden_for_read_only(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env=_read_only_env()) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/jobs/table", headers=headers)
        _assert_json_error(response, status_code=403)


@pytest.mark.parametrize(
    "path",
    [
        "/ui/spotify",
        "/ui/spotify/status",
    ],
)
def test_spotify_routes_not_found_when_feature_disabled(monkeypatch, path: str) -> None:
    """When the Spotify feature flag is off, the UI hides behind JSON 404 responses."""
    extra_env = {"UI_FEATURE_SPOTIFY": "false"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        response = client.get(path, headers={"Cookie": _cookies_header(client)})
        _assert_json_error(response, status_code=404)
        body = response.json()
        assert body == {
            "ok": False,
            "error": {
                "code": ErrorCode.NOT_FOUND.value,
                "message": "The requested UI feature is disabled.",
            },
        }


@pytest.mark.parametrize(
    "path",
    [
        "/ui/spotify",
        "/ui/spotify/status",
        "/ui/spotify/account",
        "/ui/spotify/recommendations",
        "/ui/spotify/saved",
        "/ui/spotify/playlists",
        "/ui/spotify/artists",
        "/ui/spotify/playlists/demo/tracks",
        "/ui/spotify/tracks/demo",
        "/ui/spotify/free",
        "/ui/spotify/backfill",
        "/ui/spotify/top/tracks",
        "/ui/spotify/top/artists",
    ],
)
def test_spotify_get_routes_forbidden_for_read_only(monkeypatch, path: str) -> None:
    with _create_client(monkeypatch, extra_env=_read_only_env()) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get(path, headers=headers)
        _assert_json_error(response, status_code=403)


@pytest.mark.parametrize(
    "path",
    [
        "/ui/spotify/recommendations",
        "/ui/spotify/saved/save",
        "/ui/spotify/saved/remove",
        "/ui/spotify/free/run",
        "/ui/spotify/free/upload",
        "/ui/spotify/backfill/run",
        "/ui/spotify/oauth/manual",
        "/ui/spotify/oauth/start",
    ],
)
def test_spotify_post_routes_forbidden_for_read_only(monkeypatch, path: str) -> None:
    with _create_client(monkeypatch, extra_env=_read_only_env()) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(path, headers=headers)
        _assert_json_error(response, status_code=403)


def test_watchlist_fragment_success(monkeypatch) -> None:
    stub = _StubWatchlistService(
        entries=(
            WatchlistRow(
                artist_key="spotify:artist:1",
                priority=1,
                state_key="watchlist.state.active",
            ),
            WatchlistRow(
                artist_key="spotify:artist:2",
                priority=2,
                state_key="watchlist.state.paused",
                paused=True,
            ),
        ),
    )
    app.dependency_overrides[get_watchlist_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/watchlist/table", headers=headers)
            _assert_html_response(response)
            assert "hx-watchlist-table" in response.text
            assert "spotify:artist:1" in response.text
            assert 'data-test="watchlist-priority-input-spotify-artist-1"' in response.text
            assert 'data-test="watchlist-pause-spotify-artist-1"' in response.text
            assert 'data-test="watchlist-pause-reason-spotify-artist-1"' in response.text
            assert 'data-test="watchlist-pause-resume-at-spotify-artist-1"' in response.text
            assert 'data-test="watchlist-resume-spotify-artist-2"' in response.text
            assert 'data-test="watchlist-delete-spotify-artist-1"' in response.text
            assert 'name="csrftoken"' in response.text
            assert "list" in stub.async_calls
    finally:
        app.dependency_overrides.pop(get_watchlist_ui_service, None)


def test_watchlist_create_requires_csrf(monkeypatch) -> None:
    WatchlistService().reset()
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.post(
            "/ui/watchlist",
            data={"artist_key": "spotify:artist:1"},
            headers=headers,
        )
        assert response.status_code == 403


def test_watchlist_create_success(monkeypatch) -> None:
    stub = _StubWatchlistService()
    app.dependency_overrides[get_watchlist_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            submission = client.post(
                "/ui/watchlist",
                data={"artist_key": "spotify:artist:42", "priority": "2"},
                headers=_csrf_headers(client),
            )
            _assert_html_response(submission)
            html = submission.text
            assert "spotify:artist:42" in html
            assert "<table" in html
            assert "data-count" in html
            assert stub.created == ["spotify:artist:42"]
            assert "create" in stub.async_calls
    finally:
        app.dependency_overrides.pop(get_watchlist_ui_service, None)


def test_watchlist_create_forbidden_for_read_only(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env=_read_only_env()) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(
            "/ui/watchlist",
            data={"artist_key": "spotify:artist:blocked"},
            headers=headers,
        )
        _assert_json_error(response, status_code=403)


def test_watchlist_priority_requires_csrf(monkeypatch) -> None:
    WatchlistService().reset()
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.post(
            "/ui/watchlist/spotify:artist:1/priority",
            data={"priority": "5"},
            headers=headers,
        )
        assert response.status_code == 403


def test_watchlist_priority_success(monkeypatch) -> None:
    stub = _StubWatchlistService(
        entries=(
            WatchlistRow(
                artist_key="spotify:artist:10",
                priority=1,
                state_key="watchlist.state.active",
            ),
        ),
    )
    app.dependency_overrides[get_watchlist_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/watchlist/spotify:artist:10/priority",
                data={"priority": "7"},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response)
            assert "spotify:artist:10" in response.text
            assert "7" in response.text
            assert stub.updated == [("spotify:artist:10", 7)]
            assert "update" in stub.async_calls
    finally:
        app.dependency_overrides.pop(get_watchlist_ui_service, None)


def test_watchlist_priority_forbidden_for_read_only(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env=_read_only_env()) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(
            "/ui/watchlist/spotify:artist:1/priority",
            data={"priority": "3"},
            headers=headers,
        )
        _assert_json_error(response, status_code=403)


def test_downloads_fragment_success(monkeypatch) -> None:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=1,
                filename="example.mp3",
                status="queued",
                progress=0.25,
                priority=3,
                username="tester",
                created_at=None,
                updated_at=None,
            )
        ],
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/downloads/table", headers=headers)
            _assert_html_response(response)
            body = response.text
            assert "example.mp3" in body
            assert "hx-downloads-table" in body
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_downloads_fragment_validation_error(monkeypatch) -> None:
    page = DownloadPage(items=[], limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    stub.list_exception = ValidationAppError("Invalid priority range.")
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/downloads/table", headers=headers)
            _assert_html_response(response, status_code=400)
            html = response.text
            lines = [line.strip() for line in html.splitlines() if line.strip()]
            assert lines == [
                '<div class="alerts">',
                '<p role="alert" class="alert alert--error">Invalid priority range.</p>',
                "</div>",
            ]
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_downloads_fragment_requires_feature(monkeypatch) -> None:
    extra_env = {"UI_FEATURE_DLQ": "false"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/downloads/table", headers=headers)
        assert response.status_code == 404
        assert response.headers.get("content-type", "").startswith("application/json")


def test_downloads_fragment_error(monkeypatch) -> None:
    page = DownloadPage(items=[], limit=20, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    stub.list_exception = AppError(
        "broken",
        code=ErrorCode.DEPENDENCY_ERROR,
        http_status=503,
    )
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/downloads/table", headers=headers)
            _assert_html_response(response, status_code=503)
            html = response.text
            lines = [line.strip() for line in html.splitlines() if line.strip()]
            assert lines == [
                '<div class="alerts">',
                '<p role="alert" class="alert alert--error">broken</p>',
                "</div>",
            ]
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_download_priority_requires_csrf(monkeypatch) -> None:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=5,
                filename="track.flac",
                status="running",
                progress=0.5,
                priority=5,
                username=None,
                created_at=None,
                updated_at=None,
            )
        ],
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.post(
                "/ui/downloads/5/priority",
                data={"priority": "7"},
                headers=headers,
            )
            assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_download_priority_forbidden_for_read_only(monkeypatch) -> None:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=9,
                filename="song.flac",
                status="queued",
                progress=None,
                priority=1,
                username=None,
                created_at=None,
                updated_at=None,
            )
        ],
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env=_read_only_env()) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/downloads/9/priority",
                data={"priority": "4"},
                headers=headers,
            )
            _assert_json_error(response, status_code=403)
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_download_priority_success(monkeypatch) -> None:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=7,
                filename="song.mp3",
                status="queued",
                progress=None,
                priority=1,
                username="alice",
                created_at=None,
                updated_at=None,
            )
        ],
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/downloads/7/priority",
                data={"priority": "9"},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response)
            html = response.text
            assert "song.mp3" in html
            assert "9" in html
            assert stub.updated == [(7, 9)]
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_jobs_fragment_success(monkeypatch) -> None:
    async def _fake_list_jobs(self, request):  # type: ignore[override]
        return (
            OrchestratorJob(name="sync", status="idle", enabled=True),
            OrchestratorJob(name="retry", status="failed", enabled=False),
        )

    monkeypatch.setattr("app.ui.routes.jobs.JobsUiService.list_jobs", _fake_list_jobs)

    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/jobs/table", headers=headers)
        _assert_html_response(response)
        body = response.text
        assert "sync" in body
        assert "retry" in body


def test_jobs_fragment_requires_feature(monkeypatch) -> None:
    extra_env = {"UI_FEATURE_DLQ": "false"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/jobs/table", headers=headers)
        assert response.status_code == 404
        assert response.headers.get("content-type", "").startswith("application/json")


def test_search_results_success(monkeypatch) -> None:
    page = SearchResultsPage(
        items=[
            SearchResult(
                identifier="track-1",
                title="Example",
                artist="Artist",
                source="spotify",
                score=0.8,
                bitrate=320,
                audio_format="MP3",
            )
        ],
        total=1,
        limit=25,
        offset=0,
    )
    stub = _StubSearchService(page)
    app.dependency_overrides[get_search_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/search/results",
                data={"query": "Example", "limit": "25", "sources": ["spotify"]},
                headers=headers,
            )
            _assert_html_response(response)
            body = response.text
            assert "Example" in body
            assert "spotify" in body
            assert 'data-sources="spotify"' in body
            assert stub.calls == [("Example", 25, 0, ("spotify",))]
    finally:
        app.dependency_overrides.pop(get_search_ui_service, None)


def test_search_results_render_download_action(monkeypatch) -> None:
    page = SearchResultsPage(
        items=[
            SearchResult(
                identifier="track-3",
                title="Queue Me",
                artist="Downloader",
                source="soulseek",
                score=0.9,
                bitrate=256,
                audio_format="FLAC",
                download=SearchResultDownload(
                    username="collector",
                    files=(
                        {
                            "filename": "Downloader - Queue Me.flac",
                            "download_uri": "magnet:?xt=urn:btih:queue",
                            "source": "ui-search:soulseek",
                        },
                    ),
                ),
            )
        ],
        total=1,
        limit=25,
        offset=0,
    )
    stub = _StubSearchService(page)
    app.dependency_overrides[get_search_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/search/results",
                data={"query": "Queue", "limit": "25", "sources": ["soulseek"]},
                headers=headers,
            )
            _assert_html_response(response)
            body = response.text
            assert (
                'action="/ui/search/download"' in body
                or 'action="http://testserver/ui/search/download"' in body
            )
            assert (
                'hx-post="/ui/search/download"' in body
                or 'hx-post="http://testserver/ui/search/download"' in body
            )
            assert 'name="files"' in body
            assert "Queue download" in body
    finally:
        app.dependency_overrides.pop(get_search_ui_service, None)


def test_search_results_get_pagination(monkeypatch) -> None:
    page = SearchResultsPage(
        items=[
            SearchResult(
                identifier="track-2",
                title="Example 2",
                artist="Artist",
                source="soulseek",
                score=0.7,
                bitrate=256,
                audio_format="FLAC",
            )
        ],
        total=50,
        limit=25,
        offset=25,
    )
    stub = _StubSearchService(page)
    app.dependency_overrides[get_search_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = {"Cookie": _cookies_header(client), "HX-Request": "true"}
            response = client.get(
                "/ui/search/results",
                params={
                    "query": "Example",
                    "limit": "25",
                    "offset": "25",
                    "sources": ["soulseek"],
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert "Example 2" in response.text
            assert "sources=soulseek" in response.text
            assert 'data-sources="soulseek"' in response.text
            assert stub.calls == [("Example", 25, 25, ("soulseek",))]
    finally:
        app.dependency_overrides.pop(get_search_ui_service, None)


def test_search_results_defaults_to_configured_sources(monkeypatch) -> None:
    page = SearchResultsPage(
        items=[
            SearchResult(
                identifier="track-4",
                title="Default",
                artist="Artist",
                source="spotify",
                score=0.5,
                bitrate=192,
                audio_format="MP3",
            )
        ],
        total=60,
        limit=25,
        offset=0,
    )
    stub = _StubSearchService(page)
    app.dependency_overrides[get_search_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/search/results",
                data={"query": "Default", "limit": "25"},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response)
            html = response.text
            expected_sources = tuple(DEFAULT_SOURCES)
            assert stub.calls == [("Default", 25, 0, expected_sources)]
            assert f'data-sources="{",".join(expected_sources)}"' in html
            for source in expected_sources:
                assert f"sources={source}" in html
    finally:
        app.dependency_overrides.pop(get_search_ui_service, None)


def test_search_results_requires_csrf(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        response = client.post(
            "/ui/search/results",
            data={"query": "Example"},
            headers={"Cookie": _cookies_header(client)},
        )
        assert response.status_code == 403


def test_search_results_requires_feature(monkeypatch) -> None:
    extra_env = {"UI_FEATURE_SOULSEEK": "false"}
    with _create_client(monkeypatch, extra_env=extra_env) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(
            "/ui/search/results",
            data={"query": "Example"},
            headers=headers,
        )
        assert response.status_code == 404
        assert response.headers.get("content-type", "").startswith("application/json")


def test_search_results_forbidden_for_read_only(monkeypatch) -> None:
    with _create_client(monkeypatch, extra_env=_read_only_env()) as client:
        _login(client)
        headers = _csrf_headers(client)
        response = client.post(
            "/ui/search/results",
            data={"query": "blocked"},
            headers=headers,
        )
        _assert_json_error(response, status_code=403)


def test_search_download_action_success(monkeypatch) -> None:
    stub = _StubQueueDownloadService({"status": "queued"})
    app.dependency_overrides[get_download_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            files_payload = json.dumps(
                [
                    {
                        "filename": "Queued.flac",
                        "download_uri": "magnet:?xt=urn:btih:queued",
                        "source": "ui-search:soulseek",
                    }
                ]
            )
            response = client.post(
                "/ui/search/download",
                data={
                    "identifier": "track-queued",
                    "username": "collector",
                    "files": files_payload,
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert "Queued download request for Queued.flac" in response.text
            assert len(stub.calls) == 1
            payload, worker = stub.calls[0]
            assert payload.username == "collector"
            assert payload.files[0].resolved_filename == "Queued.flac"
            assert worker is None
    finally:
        app.dependency_overrides.pop(get_download_service, None)


def test_search_download_action_app_error(monkeypatch) -> None:
    error = AppError("worker unavailable", code=ErrorCode.DEPENDENCY_ERROR, http_status=503)
    stub = _StubQueueDownloadService(error)
    app.dependency_overrides[get_download_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            files_payload = json.dumps(
                [
                    {
                        "filename": "Failure.flac",
                        "download_uri": "magnet:?xt=urn:btih:failure",
                        "source": "ui-search:soulseek",
                    }
                ]
            )
            response = client.post(
                "/ui/search/download",
                data={
                    "identifier": "track-fail",
                    "username": "collector",
                    "files": files_payload,
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response, status_code=503)
            assert "worker unavailable" in response.text
            assert len(stub.calls) == 1
    finally:
        app.dependency_overrides.pop(get_download_service, None)


def test_search_download_action_invalid_payload(monkeypatch) -> None:
    stub = _StubQueueDownloadService({"status": "queued"})
    app.dependency_overrides[get_download_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/search/download",
                data={
                    "identifier": "track-invalid",
                    "username": "",
                    "files": "",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response, status_code=400)
            assert len(stub.calls) == 0
    finally:
        app.dependency_overrides.pop(get_download_service, None)


def test_search_results_app_error(monkeypatch) -> None:
    error = AppError("search failed", code=ErrorCode.DEPENDENCY_ERROR, http_status=502)
    stub = _StubSearchService(error)
    app.dependency_overrides[get_search_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/search/results",
                data={"query": "Example"},
                headers=headers,
            )
            _assert_html_response(response, status_code=502)
            assert "search failed" in response.text
    finally:
        app.dependency_overrides.pop(get_search_ui_service, None)


def test_spotify_status_fragment_renders_forms(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub._status = SpotifyStatus(
        status="connected",
        free_available=False,
        pro_available=True,
        authenticated=True,
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/status",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "spotify-oauth-start" in response.text
            assert "spotify-manual-form" in response.text
            assert "Redirect URI" in response.text
            match = re.search(
                r'status-badge--(?P<variant>[a-z]+)"\s+data-test="spotify-status-free"',
                response.text,
            )
            assert match is not None
            assert match.group("variant") == "muted"
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_oauth_start_redirects_on_success(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/oauth/start",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers={**headers, "HX-Request": "true"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers.get("HX-Redirect") == stub.start_url
            assert response.headers.get("location") == stub.start_url
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_oauth_start_returns_alert_on_value_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.start_exception = ValueError("Temporarily unavailable")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/oauth/start",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response, status_code=503)
            assert "alert--error" in response.text
            assert "Temporarily unavailable" in response.text
            assert "HX-Redirect" not in response.headers
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_fragment_renders_table(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/saved",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "spotify-save-track-form" in response.text
            assert "Track One" in response.text
            assert "Artist One" in response.text
            assert "Album One" in response.text
            assert (
                'hx-post="/ui/spotify/saved/queue"' in response.text
                or 'hx-post="http://testserver/ui/spotify/saved/queue"' in response.text
            )
            assert (
                'hx-delete="/ui/spotify/saved/remove"' in response.text
                or 'hx-delete="http://testserver/ui/spotify/saved/remove"' in response.text
            )
            assert stub.list_saved_calls == [(25, 0)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_fragment_uses_executor(monkeypatch) -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    spotify_service = Mock()
    spotify_service.get_saved_tracks.return_value = {"items": [], "total": 0}
    executor = AsyncMock(return_value={"items": [], "total": 0})
    monkeypatch.setattr("app.ui.services.spotify._run_in_executor", executor)

    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=spotify_service,
        oauth_service=_StubOAuthService({}),
        db_session=Mock(),
    )

    app.dependency_overrides[get_spotify_ui_service] = lambda: service
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/saved",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)

    executor.assert_awaited()
    args = executor.await_args
    assert args.args[0] is spotify_service.get_saved_tracks
    assert args.kwargs == {"limit": 25, "offset": 0}


def test_spotify_top_tracks_fragment_renders_table(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            saved_response = client.get(
                "/ui/spotify/saved",
                params={"limit": 10, "offset": 30},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(saved_response)
            response = client.get(
                "/ui/spotify/top/tracks",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "Top Track" in response.text
            assert "spotify-top-tracks-table" in response.text
            assert "table-external-link-hint" in response.text
            assert "spotify-top-track-link-top-track-1" in response.text
            assert 'name="limit" value="10"' in response.text
            assert 'name="offset" value="30"' in response.text
            assert stub.top_tracks_calls == [(20, "medium_term")]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_top_tracks_fragment_returns_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.top_tracks_rows = Exception("boom")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/top/tracks",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=500)
            assert "Unable to load Spotify top tracks." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_top_artists_fragment_renders_table(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/top/artists",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "Top Artist" in response.text
            assert "spotify-top-artists-table" in response.text
            assert "table-external-link-hint" in response.text
            assert "spotify-top-artist-link-top-artist-1" in response.text
            assert stub.top_artists_calls == [(20, "medium_term")]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_top_artists_fragment_returns_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.top_artists_rows = Exception("boom")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/top/artists",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=500)
            assert "Unable to load Spotify top artists." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_fragment_renders_form(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.get(
                "/ui/spotify/recommendations",
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert "spotify-recommendations-form" in response.text
            assert "table-external-link-hint" in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_success(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            saved_response = client.get(
                "/ui/spotify/saved",
                params={"limit": 12, "offset": 18},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(saved_response)
            headers["Cookie"] = _cookies_header(client)
            response = client.post(
                "/ui/spotify/recommendations",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "seed_tracks": "track-1",
                    "seed_artists": "artist-1",
                    "seed_genres": "rock",
                    "limit": "10",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert "Recommended Track" in response.text
            assert "spotify-recommendation-seed-artist-artist-seed-1" in response.text
            assert "<strong>Artist:</strong>" in response.text
            assert "artist-seed-1" in response.text
            assert "spotify-recommendation-link-track-reco-1" in response.text
            assert "table-external-link-hint" in response.text
            assert stub.recommendations_calls == [(("track-1",), ("artist-1",), ("rock",), 10)]
            assert 'name="offset" value="18"' in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_handles_validation_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/recommendations",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "seed_tracks": " ",
                    "seed_artists": "",
                    "seed_genres": "",
                    "limit": "20",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response, status_code=400)
            assert "Provide at least one seed value." in response.text
            assert stub.recommendations_calls == []
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_handles_service_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.recommendations_exception = ValueError("Invalid seeds")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/recommendations",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "seed_tracks": "track-1",
                    "seed_artists": "",
                    "seed_genres": "",
                    "limit": "5",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response, status_code=400)
            assert "Invalid seeds" in response.text
            assert stub.recommendations_calls == [(("track-1",), (), (), 5)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_queue_action(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/recommendations",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "action": "queue",
                    "track_id": "track-1",
                    "seed_tracks": "track-1",
                    "seed_artists": "artist-1",
                    "seed_genres": "",
                    "limit": "10",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert "Queued 1 Spotify track" in response.text
            assert stub.queue_recommendation_calls == [("track-1",)]
            assert stub.recommendations_calls == [(("track-1",), ("artist-1",), (), 10)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_queue_disabled(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        extra_env = {"UI_FEATURE_IMPORTS": "false"}
        with _create_client(monkeypatch, extra_env=extra_env) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/recommendations",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "action": "queue",
                    "track_id": "track-1",
                    "seed_tracks": "track-1",
                    "seed_artists": "artist-1",
                    "seed_genres": "",
                    "limit": "10",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_json_error(response, status_code=404)
            assert stub.queue_recommendation_calls == []
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_queue_handles_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.queue_recommendation_exception = ValueError("Unable to queue tracks")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/recommendations",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "action": "queue",
                    "track_id": "track-1",
                    "seed_tracks": "track-1",
                    "seed_artists": "",
                    "seed_genres": "",
                    "limit": "10",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response, status_code=400)
            assert "Unable to queue tracks" in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_save_defaults_admin(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/recommendations",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "action": "save_defaults",
                    "seed_tracks": "track-1",
                    "seed_artists": "artist-1",
                    "seed_genres": "genre-1",
                    "limit": "10",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert "Default recommendation seeds saved." in response.text
            assert stub.save_seed_defaults_calls == [(("track-1",), ("artist-1",), ("genre-1",))]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_save_defaults_requires_admin(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/recommendations",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "action": "save_defaults",
                    "seed_tracks": "track-1",
                    "seed_artists": "artist-1",
                    "seed_genres": "genre-1",
                    "limit": "10",
                },
                headers={**headers, "HX-Request": "true"},
            )
            assert response.status_code == status.HTTP_403_FORBIDDEN
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_load_defaults_admin(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.recommendation_seed_defaults = {
        "seed_tracks": "track-2",
        "seed_artists": "artist-2",
        "seed_genres": "genre-2",
    }
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/recommendations",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "action": "load_defaults",
                    "limit": "20",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert 'value="track-2"' in response.text
            assert 'value="artist-2"' in response.text
            assert "genre-2" in response.text
            assert stub.recommendations_calls == [(("track-2",), ("artist-2",), ("genre-2",), 20)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_fragment_returns_error_on_failure(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.saved_tracks_exception = Exception("boom")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/saved",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=500)
            assert "Unable to load Spotify saved tracks." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_manual_completion_handles_validation_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.manual_result = SpotifyManualResult(ok=False, message="invalid redirect")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/oauth/manual",
                data={"redirect_url": "http://invalid"},
                headers=headers,
            )
            _assert_html_response(response)
            assert "invalid redirect" in response.text
            assert stub.manual_calls == ["http://invalid"]
            assert 'value="http://invalid"' in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_status_fragment_hides_manual_form_when_disabled(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub._oauth = SpotifyOAuthHealth(
        manual_enabled=False,
        redirect_uri=None,
        public_host_hint="https://console.example",
        active_transactions=1,
        ttl_seconds=0,
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/status",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "spotify-manual-form" not in response.text
            assert "Manual completion is disabled" in response.text
            assert "Ensure the public host is reachable" in response.text
            assert "Redirect URI" not in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_account_fragment_renders_summary(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.account_summary = SpotifyAccountSummary(
        display_name="Example User",
        email="user@example.com",
        product="Premium",
        followers=2500,
        country="GB",
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/account",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "Example User" in response.text
            assert "user@example.com" in response.text
            assert "2,500" in response.text
            assert "Premium" in response.text
            assert 'data-test="spotify-account-refresh"' in response.text
            assert 'data-test="spotify-account-reset-scopes"' not in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_account_fragment_shows_reset_for_admin(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.account_summary = SpotifyAccountSummary(
        display_name="Admin User",
        email="admin@example.com",
        product="Premium",
        followers=100,
        country="DE",
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/account",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert 'data-test="spotify-account-refresh"' in response.text
            assert 'data-test="spotify-account-reset-scopes"' in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_account_refresh_invokes_service(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/account/refresh",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert stub.refresh_account_calls == [None]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_account_reset_requires_admin(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/account/reset-scopes",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_json_error(response, status_code=status.HTTP_403_FORBIDDEN)
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_account_reset_runs_for_admin(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/account/reset-scopes",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert stub.reset_scopes_calls == [None]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_action_save_success(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/saved/save",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "track_ids": "track-99",
                    "limit": "25",
                    "offset": "0",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert "Track track-99" in response.text
            assert stub.save_calls == [("track-99",)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_pagination_cookies_insecure_by_default(
    monkeypatch,
) -> None:
    stub = _StubSpotifyService()
    stub.saved_tracks_rows = [
        SpotifySavedTrackRow(
            identifier="track-1",
            name="Track",
            artists=("Artist",),
            album="Album",
            added_at=datetime(2023, 1, 1, 12, 0),
        )
    ]
    stub.saved_tracks_total = len(stub.saved_tracks_rows)
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/saved",
                params={"limit": 15, "offset": 5},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            limit_cookie = _cookie_header(response, "spotify_saved_tracks_limit")
            offset_cookie = _cookie_header(response, "spotify_saved_tracks_offset")
            assert "secure" not in limit_cookie.lower()
            assert "secure" not in offset_cookie.lower()
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_pagination_allows_secure_cookies(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.saved_tracks_rows = [
        SpotifySavedTrackRow(
            identifier="track-1",
            name="Track",
            artists=("Artist",),
            album="Album",
            added_at=datetime(2023, 1, 1, 12, 0),
        )
    ]
    stub.saved_tracks_total = len(stub.saved_tracks_rows)
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env={"UI_COOKIES_SECURE": "true"}) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/saved",
                params={"limit": 15, "offset": 5},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            limit_cookie = _cookie_header(response, "spotify_saved_tracks_limit")
            offset_cookie = _cookie_header(response, "spotify_saved_tracks_offset")
            assert "secure" in limit_cookie.lower()
            assert "secure" in offset_cookie.lower()
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_action_save_uses_persisted_pagination(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.saved_tracks_rows = [
        SpotifySavedTrackRow(
            identifier=f"track-{index}",
            name=f"Track {index}",
            artists=(f"Artist {index}",),
            album="Album",
            added_at=datetime(2023, 1, 1, 12, 0),
        )
        for index in range(60)
    ]
    stub.saved_tracks_total = len(stub.saved_tracks_rows)
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            csrf_headers = _csrf_headers(client)
            saved_response = client.get(
                "/ui/spotify/saved",
                params={"limit": 15, "offset": 45},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(saved_response)
            action_headers = {
                "Cookie": _cookies_header(client),
                "X-CSRF-Token": csrf_headers["X-CSRF-Token"],
                "HX-Request": "true",
                "HX-Current-URL": "http://testserver/ui/spotify/saved?limit=15&offset=45",
            }
            response = client.post(
                "/ui/spotify/saved/save",
                data={
                    "csrftoken": csrf_headers["X-CSRF-Token"],
                    "track_id": "track-999",
                },
                headers=action_headers,
            )
            _assert_html_response(response)
            assert stub.save_calls[-1] == ("track-999",)
            assert stub.list_saved_calls[-1] == (15, 45)
            assert 'name="offset" value="45"' in response.text
            assert client.cookies.get("spotify_saved_tracks_offset") == "45"
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_action_queue_success(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.queue_result = SpotifyFreeIngestResult(
        ok=True,
        job_id="job-queue",
        accepted=SpotifyFreeIngestAccepted(playlists=0, tracks=2, batches=1),
        skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
        error=None,
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/saved/queue",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "track_ids": "track-queue-1, track-queue-2",
                    "limit": "25",
                    "offset": "0",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert stub.queue_calls == [("track-queue-1", "track-queue-2")]
            assert "Queue download" in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_action_queue_disabled(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        extra_env = {"UI_FEATURE_IMPORTS": "false"}
        with _create_client(monkeypatch, extra_env=extra_env) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/saved/queue",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "track_ids": "track-queue-1",
                    "limit": "25",
                    "offset": "0",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_json_error(response, status_code=404)
            assert stub.queue_calls == []
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_action_remove_handles_value_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.remove_exception = ValueError("At least one Spotify track identifier is required.")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.request(
                "DELETE",
                "/ui/spotify/saved/remove",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "track_id": "",
                    "limit": "25",
                    "offset": "0",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response, status_code=400)
            assert "At least one Spotify track identifier is required." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_action_remove_success(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.request(
                "DELETE",
                "/ui/spotify/saved/remove",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "track_id": "track-1",
                    "limit": "25",
                    "offset": "0",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert "No Spotify tracks are currently saved" in response.text
            assert stub.remove_calls == [("track-1",)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_action_remove_uses_persisted_pagination(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.saved_tracks_rows = [
        SpotifySavedTrackRow(
            identifier=f"track-{index}",
            name=f"Track {index}",
            artists=(f"Artist {index}",),
            album="Album",
            added_at=datetime(2023, 1, 1, 12, 0),
        )
        for index in range(60)
    ]
    stub.saved_tracks_total = len(stub.saved_tracks_rows)
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            csrf_headers = _csrf_headers(client)
            saved_response = client.get(
                "/ui/spotify/saved",
                params={"limit": 15, "offset": 30},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(saved_response)
            action_headers = {
                "Cookie": _cookies_header(client),
                "X-CSRF-Token": csrf_headers["X-CSRF-Token"],
                "HX-Request": "true",
                "HX-Current-URL": "http://testserver/ui/spotify/saved?limit=15&offset=30",
            }
            response = client.request(
                "DELETE",
                "/ui/spotify/saved/remove",
                data={
                    "csrftoken": csrf_headers["X-CSRF-Token"],
                    "track_id": "track-5",
                },
                headers=action_headers,
            )
            _assert_html_response(response)
            assert stub.remove_calls[-1] == ("track-5",)
            assert stub.list_saved_calls[-1] == (15, 30)
            assert 'name="offset" value="30"' in response.text
            assert client.cookies.get("spotify_saved_tracks_offset") == "30"
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_saved_tracks_action_queue_handles_value_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.queue_exception = ValueError("At least one Spotify track identifier is required.")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/saved/queue",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "track_ids": " ",
                    "limit": "25",
                    "offset": "0",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response, status_code=400)
            assert "At least one Spotify track identifier is required." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_track_detail_modal_renders_modal(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.track_detail_result = SpotifyTrackDetail(
        track_id="track-42",
        name="Modal Track",
        artists=("Artist A", "Artist B"),
        album="Album Z",
        release_date="2023-01-01",
        duration_ms=200000,
        popularity=64,
        explicit=True,
        preview_url="https://preview.example/track-42",
        external_url="https://open.spotify.com/track/track-42",
        detail={},
        features={},
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/tracks/track-42",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "spotify-track-detail-modal" in response.text
            assert "Modal Track" in response.text
            assert stub.track_detail_calls == ["track-42"]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_track_detail_modal_handles_service_value_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.track_detail_exception = ValueError("invalid track")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/tracks/invalid",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=400)
            assert "invalid track" in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_track_detail_modal_handles_exception(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.track_detail_exception = Exception("boom")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/tracks/track-1",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=500)
            assert "Unable to load Spotify track details." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_account_fragment_returns_error_on_failure(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.account_exception = Exception("boom")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/account",
                headers={"Cookie": _cookies_header(client)},
            )
            assert response.status_code == 500
            assert "Unable to load Spotify account details." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlists_fragment_returns_error_on_failure(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlists = Exception("boom")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/playlists",
                headers={"Cookie": _cookies_header(client)},
            )
            assert response.status_code == 500
            assert "Unable to load Spotify playlists." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlists_filter_updates_fragment(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlists = (
        SpotifyPlaylistRow(
            identifier="playlist-1",
            name="Example",
            track_count=10,
            updated_at=datetime(2023, 9, 1, 12, 0, tzinfo=UTC),
            owner="Owner A",
            owner_id="owner-a",
            follower_count=12,
            sync_status="fresh",
        ),
    )
    stub.filter_options = SpotifyPlaylistFilters(
        owners=(SpotifyPlaylistFilterOption(value="owner-a", label="Owner A"),),
        sync_statuses=(SpotifyPlaylistFilterOption(value="fresh", label="Fresh"),),
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/playlists/filter",
                data={
                    "owner": "owner-a",
                    "status": "fresh",
                    "csrftoken": headers["X-CSRF-Token"],
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert "Owner A" in response.text
            assert 'value="owner-a" selected' in response.text
            assert stub.list_playlists_calls == [("owner-a", "fresh")]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlists_refresh_triggers_service(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlists = (
        SpotifyPlaylistRow(
            identifier="playlist-2",
            name="Daily Mix",
            track_count=5,
            updated_at=datetime(2023, 9, 2, 9, 0, tzinfo=UTC),
            owner="Owner B",
            owner_id="owner-b",
            follower_count=20,
            sync_status="fresh",
        ),
    )
    stub.filter_options = SpotifyPlaylistFilters(
        owners=(),
        sync_statuses=(),
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/playlists/refresh",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response)
            assert stub.refresh_calls == [None]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlists_force_sync_requires_admin(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/playlists/force-sync",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_json_error(response, status_code=status.HTTP_403_FORBIDDEN)
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlists_force_sync_runs_for_admin(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlists = (
        SpotifyPlaylistRow(
            identifier="playlist-3",
            name="Release Radar",
            track_count=30,
            updated_at=datetime(2023, 9, 3, 8, 30, tzinfo=UTC),
            owner="Owner C",
            owner_id="owner-c",
            follower_count=55,
            sync_status="stale",
        ),
    )
    stub.filter_options = SpotifyPlaylistFilters(
        owners=(),
        sync_statuses=(),
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch, extra_env={"UI_ROLE_DEFAULT": "admin"}) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/playlists/force-sync",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response)
            assert stub.force_sync_calls == [None]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlist_items_fragment_renders_table(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlist_items_rows = (
        SpotifyPlaylistItemRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist One",),
            album="Album One",
            added_at=datetime(2023, 9, 1, 12, 0),
            added_by="Curator",
            is_local=False,
            metadata={},
        ),
    )
    stub.playlist_items_total = 5
    stub.playlist_items_page_limit = 25
    stub.playlist_items_page_offset = 0
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/playlists/playlist-1/tracks",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "spotify-playlist-items-table" in response.text
            assert "Track One" in response.text
            assert stub.playlist_items_calls == [("playlist-1", 25, 0)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlist_items_fragment_forwards_query_bounds(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlist_items_rows = ()
    stub.playlist_items_total = 0
    stub.playlist_items_page_limit = 10
    stub.playlist_items_page_offset = 5
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/playlists/playlist-2/tracks",
                params={"limit": 10, "offset": 5, "name": "Example"},
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "No tracks to display." in response.text
            assert stub.playlist_items_calls == [("playlist-2", 10, 5)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlist_items_fragment_handles_validation_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlist_items_exception = ValueError("bad request")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/playlists/playlist-3/tracks",
                headers={"Cookie": _cookies_header(client)},
            )
            assert response.status_code == 400
            assert "bad request" in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlist_items_fragment_returns_error_on_failure(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlist_items_exception = Exception("boom")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/playlists/playlist-4/tracks",
                headers={"Cookie": _cookies_header(client)},
            )
            assert response.status_code == 500
            assert "Unable to load Spotify playlist tracks." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_artists_fragment_renders_table(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.artists = (
        SpotifyArtistRow(
            identifier="artist-1",
            name="Artist One",
            followers=1200,
            popularity=75,
            genres=("rock", "pop"),
            external_url="https://open.spotify.com/artist/artist-1",
        ),
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/artists",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "spotify-artists-table" in response.text
            assert "Artist One" in response.text
            assert "table-external-link-hint" in response.text
            assert "spotify-artist-link-artist-1" in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_artists_fragment_returns_error_on_failure(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.artists = Exception("boom")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/artists",
                headers={"Cookie": _cookies_header(client)},
            )
            assert response.status_code == 500
            assert "Unable to load Spotify artists." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_backfill_fragment_includes_timeline(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.backfill_timeline_entries = (
        SpotifyBackfillTimelineEntry(
            identifier="history-1",
            state="completed",
            requested=25,
            processed=25,
            matched=20,
            cache_hits=12,
            cache_misses=3,
            expanded_playlists=1,
            expanded_tracks=8,
            expand_playlists=False,
            include_cached_results=False,
            duration_ms=1456,
            error=None,
            created_at=datetime(2023, 8, 1, 9, 0, tzinfo=UTC),
            updated_at=datetime(2023, 8, 1, 9, 5, tzinfo=UTC),
            created_display="2023-08-01 09:00",
            updated_display="2023-08-01 09:05",
        ),
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/backfill",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "spotify-backfill-timeline" in response.text
            assert "history-1" in response.text
            assert stub.backfill_timeline_calls == [10]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_backfill_run_returns_success_alert(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.backfill_status_payload = {
        "id": "job-1",
        "state": "queued",
        "requested": 5,
        "processed": 0,
        "matched": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "expanded_playlists": 0,
        "expanded_tracks": 0,
        "duration_ms": None,
        "error": None,
        "expand_playlists": True,
        "include_cached_results": True,
    }
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/backfill/run",
                data={
                    "max_items": "25",
                    "expand_playlists": "1",
                    "include_cached_results": "1",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert "Backfill job job-1 enqueued." in response.text
            assert stub.run_calls == [(25, True, True)]
            assert stub.backfill_status_calls[-1] == "job-1"
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_backfill_run_can_disable_cache(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.backfill_status_payload = {
        "id": "job-9",
        "state": "queued",
        "requested": 5,
        "processed": 0,
        "matched": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "expanded_playlists": 0,
        "expanded_tracks": 0,
        "duration_ms": None,
        "error": None,
        "expand_playlists": True,
        "include_cached_results": False,
    }
    stub.run_backfill_job_id = "job-9"
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/backfill/run",
                data={
                    "max_items": "10",
                    "expand_playlists": "1",
                    "include_cached_results": "0",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert "Backfill job job-9 enqueued." in response.text
            assert stub.run_calls == [(10, True, False)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_backfill_pause_returns_fragment(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/backfill/pause",
                data={"job_id": "job-1"},
                headers=headers,
            )
            _assert_html_response(response)
            assert "Backfill job job-1 paused." in response.text
            assert stub.pause_backfill_calls == ["job-1"]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_backfill_resume_returns_fragment(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/backfill/resume",
                data={"job_id": "job-1"},
                headers=headers,
            )
            _assert_html_response(response)
            assert "Backfill job job-1 resumed." in response.text
            assert stub.resume_backfill_calls == ["job-1"]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_backfill_cancel_returns_fragment(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/backfill/cancel",
                data={"job_id": "job-1"},
                headers=headers,
            )
            _assert_html_response(response)
            assert "Backfill job job-1 cancelled." in response.text
            assert stub.cancel_backfill_calls == ["job-1"]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_backfill_pause_requires_job_id(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/backfill/pause",
                data={},
                headers=headers,
            )
            assert response.status_code == 400
            assert "identifier is required" in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_backfill_pause_returns_forbidden(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.pause_backfill_exception = PermissionError("no auth")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/backfill/pause",
                data={"job_id": "job-1"},
                headers=headers,
            )
            assert response.status_code == 403
            assert "Spotify authentication is required" in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_free_ingest_fragment_renders_form(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.free_ingest_status_result = SpotifyFreeIngestJobSnapshot(
        job_id="job-free",
        state="running",
        counts=SpotifyFreeIngestJobCounts(
            registered=2,
            normalized=2,
            queued=1,
            completed=1,
            failed=0,
        ),
        accepted=SpotifyFreeIngestAccepted(playlists=1, tracks=3, batches=1),
        skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
        queued_tracks=2,
        failed_tracks=0,
        skipped_tracks=0,
        skip_reason=None,
        error=None,
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/free",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "spotify-free-ingest-form" in response.text
            assert 'id="hx-import-result"' in response.text
            assert 'hx-target="#hx-import-result"' in response.text
            assert "job-free" in response.text
            assert stub.free_ingest_status_calls[-1] is None
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_free_ingest_fragment_polls_existing_job(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            session_id = client.cookies.get("ui_session")
            assert session_id
            manager = client.app.state.ui_session_manager
            asyncio.run(manager.set_spotify_free_ingest_job_id(session_id, "job-free"))
            response = client.get(
                "/ui/spotify/free",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert stub.free_ingest_status_calls[-1] == "job-free"
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_free_ingest_run_returns_fragment(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.free_import_result = SpotifyFreeIngestResult(
        ok=True,
        job_id="job-free",
        accepted=SpotifyFreeIngestAccepted(playlists=1, tracks=2, batches=1),
        skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
        error=None,
    )
    stub.free_ingest_status_result = SpotifyFreeIngestJobSnapshot(
        job_id="job-free",
        state="running",
        counts=SpotifyFreeIngestJobCounts(
            registered=1,
            normalized=1,
            queued=1,
            completed=0,
            failed=0,
        ),
        accepted=SpotifyFreeIngestAccepted(playlists=1, tracks=2, batches=1),
        skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
        queued_tracks=3,
        failed_tracks=0,
        skipped_tracks=0,
        skip_reason=None,
        error=None,
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/free/run",
                data={
                    "playlist_links": "https://open.spotify.com/playlist/demo",
                    "tracks": "Artist - Track",
                },
                headers=headers,
            )
            _assert_html_response(response)
            assert 'hx-target="#hx-import-result"' in response.text
            assert "job-free" in response.text
            assert "Queued tracks" in response.text
            assert stub.free_import_calls == [
                (("https://open.spotify.com/playlist/demo",), ("Artist - Track",))
            ]
            assert stub.free_ingest_status_calls[-1] == "job-free"
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_free_ingest_run_requires_input(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/free/run",
                data={"playlist_links": "", "tracks": ""},
                headers=headers,
            )
            _assert_html_response(response)
            assert 'hx-target="#hx-import-result"' in response.text
            assert "Provide at least one playlist link or track entry." in response.text
            assert stub.free_import_calls == []
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_free_ingest_upload_returns_fragment(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.free_ingest_status_result = SpotifyFreeIngestJobSnapshot(
        job_id="job-free",
        state="running",
        counts=SpotifyFreeIngestJobCounts(
            registered=1,
            normalized=1,
            queued=1,
            completed=0,
            failed=0,
        ),
        accepted=SpotifyFreeIngestAccepted(playlists=1, tracks=2, batches=1),
        skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
        queued_tracks=3,
        failed_tracks=0,
        skipped_tracks=0,
        skip_reason=None,
        error=None,
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/free/upload",
                data={"csrftoken": headers["X-CSRF-Token"]},
                files={"file": ("tracks.txt", b"Artist - Track", "text/plain")},
                headers=headers,
            )
            _assert_html_response(response)
            assert 'hx-target="#hx-import-result"' in response.text
            assert "Free ingest job job-free enqueued." in response.text
            assert stub.free_upload_calls[0][0] == "tracks.txt"
            assert stub.free_import_calls == [(tuple(), ("Artist - Track",))]
            assert stub.free_ingest_status_calls[-1] == "job-free"
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_free_ingest_upload_handles_validation_error(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.free_upload_exception = ValueError("file too large")
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/free/upload",
                data={"csrftoken": headers["X-CSRF-Token"]},
                files={"file": ("tracks.txt", b"bad", "text/plain")},
                headers=headers,
            )
            assert response.status_code == 400
            assert "file too large" in response.text
            assert stub.free_upload_calls
            assert stub.free_ingest_status_calls == []
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_free_ingest_fragment_disabled(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        extra_env = {"UI_FEATURE_IMPORTS": "false"}
        with _create_client(monkeypatch, extra_env=extra_env) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/free",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_json_error(response, status_code=404)
            assert stub.free_ingest_status_calls == []
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_free_ingest_run_disabled(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        extra_env = {"UI_FEATURE_IMPORTS": "false"}
        with _create_client(monkeypatch, extra_env=extra_env) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/free/run",
                data={
                    "playlist_links": "https://open.spotify.com/playlist/demo",
                    "tracks": "Artist - Track",
                },
                headers=headers,
            )
            _assert_json_error(response, status_code=404)
            assert stub.free_import_calls == []
            assert stub.free_ingest_status_calls == []
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_free_ingest_upload_disabled(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        extra_env = {"UI_FEATURE_IMPORTS": "false"}
        with _create_client(monkeypatch, extra_env=extra_env) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/free/upload",
                data={"csrftoken": headers["X-CSRF-Token"]},
                files={"file": ("tracks.txt", b"Artist - Track", "text/plain")},
                headers=headers,
            )
            _assert_json_error(response, status_code=404)
            assert stub.free_upload_calls == []
            assert stub.free_import_calls == []
            assert stub.free_ingest_status_calls == []
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)
