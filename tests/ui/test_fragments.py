from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
import json
import re
from typing import Any

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.search import DEFAULT_SOURCES
from app.config import SecurityConfig, SoulseekConfig
from app.dependencies import get_download_service, get_soulseek_client
from app.errors import AppError, ErrorCode
from app.integrations.health import IntegrationHealth, ProviderHealth
from app.main import app
from app.schemas import StatusResponse
from app.services.watchlist_service import WatchlistService
from app.ui.services import (
    ActivityPage,
    DownloadPage,
    DownloadRow,
    OrchestratorJob,
    SearchResult,
    SearchResultDownload,
    SearchResultsPage,
    SoulseekUploadRow,
    SpotifyArtistRow,
    SpotifyAccountSummary,
    SpotifyBackfillSnapshot,
    SpotifyManualResult,
    SpotifyOAuthHealth,
    SpotifyPlaylistRow,
    SpotifyRecommendationRow,
    SpotifyRecommendationSeed,
    SpotifySavedTrackRow,
    SpotifyTopArtistRow,
    SpotifyTopTrackRow,
    SpotifyStatus,
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
from tests.ui.test_ui_auth import _assert_html_response, _create_client


def _cookies_header(client: TestClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


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


def _read_only_env() -> dict[str, str]:
    fingerprint = fingerprint_api_key("primary-key")
    return {"UI_ROLE_OVERRIDES": f"{fingerprint}:read_only"}


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


class _RecordingDownloadsService:
    def __init__(self, page: DownloadPage) -> None:
        page.items = list(page.items)
        self.page = page
        self.list_exception: Exception | None = None
        self.update_exception: Exception | None = None
        self.updated: list[tuple[int, int]] = []

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
            )
        return new_row


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
            product="Premium",
            followers=1200,
            country="US",
        )
        self.account_exception: Exception | None = None
        self.playlists: Sequence[SpotifyPlaylistRow] | Exception = ()
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
            ),
        )
        self.recommendation_rows: Sequence[SpotifyRecommendationRow] = (
            SpotifyRecommendationRow(
                identifier="track-reco-1",
                name="Recommended Track",
                artists=("Reco Artist",),
                album="Reco Album",
                preview_url=None,
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
        )
        self.run_backfill_job_id = "job-1"
        self.run_backfill_exception: Exception | None = None
        self.manual_calls: list[str] = []
        self.backfill_snapshot_calls: list[tuple[str, str | None, Mapping[str, object] | None]] = []
        self.backfill_status_calls: list[str | None] = []
        self.run_calls: list[tuple[int | None, bool]] = []
        self.list_saved_calls: list[tuple[int, int]] = []
        self.top_tracks_calls: list[int] = []
        self.top_artists_calls: list[int] = []
        self.save_calls: list[tuple[str, ...]] = []
        self.remove_calls: list[tuple[str, ...]] = []
        self.playlist_add_calls: list[tuple[str, tuple[str, ...]]] = []
        self.playlist_remove_calls: list[tuple[str, tuple[str, ...]]] = []
        self.playlist_reorder_calls: list[tuple[str, int, int]] = []
        self.save_exception: Exception | None = None
        self.remove_exception: Exception | None = None
        self.playlist_add_exception: Exception | None = None
        self.playlist_remove_exception: Exception | None = None
        self.playlist_reorder_exception: Exception | None = None

    def status(self) -> SpotifyStatus:
        return self._status

    def oauth_health(self) -> SpotifyOAuthHealth:
        return self._oauth

    def list_playlists(self) -> Sequence[SpotifyPlaylistRow]:
        if isinstance(self.playlists, Exception):
            raise self.playlists
        return tuple(self.playlists)

    def _mutate_playlist(
        self, playlist_id: str, *, delta: int = 0
    ) -> None:
        if isinstance(self.playlists, Exception):
            return
        updated: list[SpotifyPlaylistRow] = []
        for row in self.playlists:
            if row.identifier == playlist_id:
                updated.append(
                    replace(row, track_count=max(0, row.track_count + delta))
                )
            else:
                updated.append(row)
        self.playlists = tuple(updated)

    def add_tracks_to_playlist(self, playlist_id: str, uris: Sequence[str]) -> int:
        if self.playlist_add_exception:
            raise self.playlist_add_exception
        cleaned = tuple(uris)
        self.playlist_add_calls.append((playlist_id, cleaned))
        self._mutate_playlist(playlist_id, delta=len(cleaned))
        return len(cleaned)

    def remove_tracks_from_playlist(self, playlist_id: str, uris: Sequence[str]) -> int:
        if self.playlist_remove_exception:
            raise self.playlist_remove_exception
        cleaned = tuple(uris)
        self.playlist_remove_calls.append((playlist_id, cleaned))
        self._mutate_playlist(playlist_id, delta=-len(cleaned))
        return len(cleaned)

    def reorder_playlist(
        self, playlist_id: str, *, range_start: int, insert_before: int
    ) -> None:
        if self.playlist_reorder_exception:
            raise self.playlist_reorder_exception
        self.playlist_reorder_calls.append((playlist_id, range_start, insert_before))

    def list_followed_artists(self) -> Sequence[SpotifyArtistRow]:
        if isinstance(self.artists, Exception):
            raise self.artists
        return tuple(self.artists)

    def top_tracks(self, *, limit: int = 20) -> Sequence[SpotifyTopTrackRow]:
        self.top_tracks_calls.append(limit)
        if isinstance(self.top_tracks_rows, Exception):
            raise self.top_tracks_rows
        return tuple(self.top_tracks_rows)

    def top_artists(self, *, limit: int = 20) -> Sequence[SpotifyTopArtistRow]:
        self.top_artists_calls.append(limit)
        if isinstance(self.top_artists_rows, Exception):
            raise self.top_artists_rows
        return tuple(self.top_artists_rows)

    def recommendations(
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

    def list_saved_tracks(
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

    def account(self) -> SpotifyAccountSummary | None:
        if self.account_exception:
            raise self.account_exception
        return self.account_summary

    async def manual_complete(self, *, redirect_url: str) -> SpotifyManualResult:
        if self.manual_exception:
            raise self.manual_exception
        self.manual_calls.append(redirect_url)
        return self.manual_result

    def start_oauth(self) -> str:
        if self.start_exception:
            raise self.start_exception
        return self.start_url

    async def run_backfill(self, *, max_items: int | None, expand_playlists: bool) -> str:
        if self.run_backfill_exception:
            raise self.run_backfill_exception
        self.run_calls.append((max_items, expand_playlists))
        return self.run_backfill_job_id

    def save_tracks(self, track_ids: Sequence[str]) -> int:
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

    def remove_saved_tracks(self, track_ids: Sequence[str]) -> int:
        if self.remove_exception:
            raise self.remove_exception
        cleaned = tuple(track_ids)
        self.remove_calls.append(cleaned)
        remaining = [row for row in self.saved_tracks_rows if row.identifier not in cleaned]
        removed = len(self.saved_tracks_rows) - len(remaining)
        self.saved_tracks_rows = remaining
        self.saved_tracks_total = len(self.saved_tracks_rows)
        return removed

    def backfill_status(self, job_id: str | None) -> Mapping[str, object] | None:
        self.backfill_status_calls.append(job_id)
        return self.backfill_status_payload

    def build_backfill_snapshot(
        self,
        *,
        csrf_token: str,
        job_id: str | None,
        status_payload: Mapping[str, object] | None,
    ) -> SpotifyBackfillSnapshot:
        self.backfill_snapshot_calls.append((csrf_token, job_id, status_payload))
        return self.snapshot


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

    def list_entries(self, request) -> WatchlistTable:  # type: ignore[override]
        return WatchlistTable(entries=tuple(self.entries))

    def create_entry(
        self,
        request,
        *,
        artist_key: str,
        priority: int | None = None,
    ) -> WatchlistTable:
        row = WatchlistRow(
            artist_key=artist_key,
            priority=priority if priority is not None else 0,
            state_key="watchlist.state.active",
        )
        self.entries.insert(0, row)
        self.created.append(artist_key)
        return WatchlistTable(entries=tuple(self.entries))

    def update_priority(
        self,
        request,
        *,
        artist_key: str,
        priority: int,
    ) -> WatchlistTable:
        self.updated.append((artist_key, priority))
        row = WatchlistRow(
            artist_key=artist_key,
            priority=priority,
            state_key="watchlist.state.active",
        )
        self.entries = [row] + [entry for entry in self.entries if entry.artist_key != artist_key]
        return WatchlistTable(entries=tuple(self.entries))


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
            _require_auth_default=False,
            _rate_limiting_default=True,
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
            assert "Enabled" in response.text
            assert "token" not in response.text
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
        with _create_client(monkeypatch) as client:
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
            assert stub.upload_calls == [False]
    finally:
        app.dependency_overrides.pop(get_soulseek_ui_service, None)


def test_soulseek_uploads_fragment_handles_error(monkeypatch) -> None:
    stub = _StubSoulseekUiService()
    stub.upload_exception = HTTPException(status_code=502, detail="boom")
    app.dependency_overrides[get_soulseek_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/soulseek/uploads",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response, status_code=502)
            assert "boom" in response.text
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
        with _create_client(monkeypatch) as client:
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
            assert "retry.flac" in html
            assert "Retries" in html
            assert "network timeout" in html
            assert "Active downloads" in html
            assert "hx-soulseek-downloads" in html
            assert 'data-scope="active"' in html
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_soulseek_downloads_fragment_all_scope(monkeypatch) -> None:
    page = DownloadPage(items=[], limit=50, offset=0, has_next=False, has_previous=False)
    stub = _RecordingDownloadsService(page)
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
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
    finally:
        app.dependency_overrides.pop(get_downloads_ui_service, None)


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

    monkeypatch.setattr("app.ui.router.soulseek_requeue_download", _fake_requeue)

    try:
        with _create_client(monkeypatch) as client:
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

    monkeypatch.setattr("app.ui.router.soulseek_requeue_download", _fail_requeue)

    try:
        with _create_client(monkeypatch) as client:
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

    monkeypatch.setattr("app.ui.router.soulseek_cancel", _fake_cancel)

    try:
        with _create_client(monkeypatch) as client:
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

    monkeypatch.setattr("app.ui.router.soulseek_cancel", _fail_cancel)

    try:
        with _create_client(monkeypatch) as client:
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
            assert "broken" in response.text
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

    monkeypatch.setattr("app.ui.router.JobsUiService.list_jobs", _fake_list_jobs)

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
                'hx-delete="/ui/spotify/saved/remove"' in response.text
                or 'hx-delete="http://testserver/ui/spotify/saved/remove"' in response.text
            )
            assert stub.list_saved_calls == [(25, 0)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_top_tracks_fragment_renders_table(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.get(
                "/ui/spotify/top/tracks",
                headers={"Cookie": _cookies_header(client)},
            )
            _assert_html_response(response)
            assert "Top Track" in response.text
            assert "spotify-top-tracks-table" in response.text
            assert stub.top_tracks_calls == [20]
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
            assert stub.top_artists_calls == [20]
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
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_recommendations_submit_success(monkeypatch) -> None:
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
            assert stub.recommendations_calls == [(("track-1",), ("artist-1",), ("rock",), 10)]
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
            assert "2,500" in response.text
            assert "Premium" in response.text
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


def test_spotify_playlist_tracks_action_add_success(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlists = (
        SpotifyPlaylistRow(
            identifier="playlist-1",
            name="Daily Mix",
            track_count=1,
            updated_at=datetime.now(tz=UTC),
        ),
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/playlists/playlist-1/tracks/add",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "uris": "spotify:track:123 spotify:track:456",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert stub.playlist_add_calls == [
                ("playlist-1", ("spotify:track:123", "spotify:track:456"))
            ]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlist_tracks_action_rejects_empty_payload(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/playlists/playlist-1/tracks/add",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers={**headers, "HX-Request": "true"},
            )
            assert response.status_code == 400
            assert "Provide at least one Spotify track URI." in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlist_tracks_action_handles_failure(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlist_add_exception = RuntimeError("boom")
    stub.playlists = (
        SpotifyPlaylistRow(
            identifier="playlist-1",
            name="Daily Mix",
            track_count=1,
            updated_at=datetime.now(tz=UTC),
        ),
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/playlists/playlist-1/tracks/add",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "uris": "spotify:track:123",
                },
                headers={**headers, "HX-Request": "true"},
            )
            assert response.status_code == 500
            assert "Unable to update the Spotify playlist" in response.text
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlist_reorder_success(monkeypatch) -> None:
    stub = _StubSpotifyService()
    stub.playlists = (
        SpotifyPlaylistRow(
            identifier="playlist-1",
            name="Daily Mix",
            track_count=1,
            updated_at=datetime.now(tz=UTC),
        ),
    )
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/playlists/playlist-1/reorder",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "range_start": "1",
                    "insert_before": "3",
                },
                headers={**headers, "HX-Request": "true"},
            )
            _assert_html_response(response)
            assert stub.playlist_reorder_calls == [("playlist-1", 1, 3)]
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)


def test_spotify_playlist_reorder_validates_positions(monkeypatch) -> None:
    stub = _StubSpotifyService()
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/playlists/playlist-1/reorder",
                data={
                    "csrftoken": headers["X-CSRF-Token"],
                    "range_start": "",
                    "insert_before": "1",
                },
                headers={**headers, "HX-Request": "true"},
            )
            assert response.status_code == 400
            assert "Provide both start and target positions" in response.text
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
    }
    app.dependency_overrides[get_spotify_ui_service] = lambda: stub
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/spotify/backfill/run",
                data={"max_items": "25", "expand_playlists": "1"},
                headers=headers,
            )
            _assert_html_response(response)
            assert "Backfill job job-1 enqueued." in response.text
            assert stub.run_calls == [(25, True)]
            assert stub.backfill_status_calls[-1] == "job-1"
    finally:
        app.dependency_overrides.pop(get_spotify_ui_service, None)
