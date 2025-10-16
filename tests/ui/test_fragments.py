from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import re

from fastapi.testclient import TestClient

from app.errors import AppError, ErrorCode
from app.main import app
from app.services.watchlist_service import WatchlistService
from app.ui.services import (
    ActivityPage,
    DownloadPage,
    DownloadRow,
    OrchestratorJob,
    SearchResult,
    SearchResultsPage,
    WatchlistRow,
    WatchlistTable,
    get_activity_ui_service,
    get_downloads_ui_service,
    get_search_ui_service,
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
        self.calls: list[tuple[str, int, Sequence[str]]] = []

    async def search(
        self,
        request,
        *,
        query: str,
        limit: int,
        sources: Sequence[str] | None = None,
    ) -> SearchResultsPage:
        if isinstance(self._result, Exception):
            raise self._result
        self.calls.append((query, limit, tuple(sources or [])))
        return self._result


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
            assert stub.calls == [("Example", 25, ("spotify",))]
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
