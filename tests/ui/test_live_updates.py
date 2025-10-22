import asyncio
import json
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.db import get_session, session_scope
from app.models import Download
from app.services.download_service import DownloadService
from app.ui.context.downloads import build_downloads_fragment_context
from app.ui.routes.shared import _LiveFragmentBuilder, _ui_event_stream, templates
from app.ui.services import (
    ActivityPage,
    DownloadPage,
    WatchlistTable,
    get_activity_ui_service,
    get_downloads_ui_service,
    get_jobs_ui_service,
    get_watchlist_ui_service,
)
from app.ui.services.downloads import DownloadsUiService
from tests.ui.test_operations_pages import _cookies_header
from tests.ui.test_ui_auth import _create_client


def _login(client: TestClient, api_key: str = "primary-key") -> None:
    response = client.post("/ui/login", data={"api_key": api_key}, follow_redirects=False)
    assert response.status_code == 303


def test_ui_events_disabled_without_flag(monkeypatch) -> None:
    with _create_client(monkeypatch) as client:
        _login(client)
        headers = {"Cookie": _cookies_header(client)}
        response = client.get("/ui/events", headers=headers)
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_ui_event_stream_emits_payload() -> None:
    async def _build_payload() -> dict[str, object]:
        return {
            "fragment_id": "hx-downloads-table",
            "event": "downloads",
            "html": '<div id="hx-downloads-table"></div>',
            "data_attributes": {"limit": "20", "offset": "0"},
        }

    builder = _LiveFragmentBuilder(name="downloads", interval=0.1, build=_build_payload)

    class _StubRequest:
        def __init__(self) -> None:
            self.cookies = {}
            self._calls = 0

        async def is_disconnected(self) -> bool:
            self._calls += 1
            return self._calls > 1

    request = _StubRequest()
    stream = _ui_event_stream(request, [builder])
    chunk = None
    async for chunk in stream:
        break

    assert chunk is not None
    assert "event: fragment" in chunk
    assert "hx-downloads-table" in chunk


@pytest.mark.asyncio
async def test_ui_event_stream_emits_heartbeat_when_idle(monkeypatch) -> None:
    fake_time = 0.0
    real_sleep = asyncio.sleep

    async def _fast_sleep(duration: float) -> None:
        nonlocal fake_time
        fake_time += duration
        await real_sleep(0)

    def _fake_monotonic() -> float:
        return fake_time

    monkeypatch.setattr("app.ui.routes.shared.time.monotonic", _fake_monotonic)
    monkeypatch.setattr("app.ui.routes.shared.asyncio.sleep", _fast_sleep)

    async def _idle_builder() -> None:
        return None

    builder = _LiveFragmentBuilder(name="idle", interval=100.0, build=_idle_builder)

    class _StubRequest:
        def __init__(self) -> None:
            self.cookies = {}
            self._calls = 0

        async def is_disconnected(self) -> bool:
            self._calls += 1
            return self._calls > 200

    request = _StubRequest()
    stream = _ui_event_stream(request, [builder])

    async for chunk in stream:
        if chunk == ": keep-alive\n\n":
            break
        pytest.fail(f"unexpected event chunk: {chunk!r}")
    else:  # pragma: no cover - defensive guard if generator exhausts early
        pytest.fail("event stream terminated without heartbeat")


@pytest.mark.asyncio
async def test_ui_event_stream_renders_downloads_fragment(monkeypatch) -> None:
    class _StubTransfersApi:
        async def get_download_queue(self, download_id: int) -> dict[str, Any]:
            return {"download_id": download_id, "status": "running"}

    with _create_client(monkeypatch, extra_env={"UI_LIVE_UPDATES": "SSE"}):
        with session_scope() as session:
            session.add(
                Download(
                    filename="active.flac",
                    state="queued",
                    progress=0.5,
                    priority=5,
                    username="tester",
                )
            )

        db_session = get_session()

        async def _session_runner(func):
            return func(db_session)

        downloads_service = DownloadsUiService(
            DownloadService(
                session=db_session,
                session_runner=_session_runner,
                transfers=_StubTransfersApi(),
            )
        )

        class _StubRequest:
            def __init__(self) -> None:
                self.cookies = {"csrftoken": "token"}
                self._calls = 0

            async def is_disconnected(self) -> bool:
                self._calls += 1
                return self._calls > 1

            def url_for(self, *args: Any, **kwargs: Any) -> str:
                raise RuntimeError("routing unavailable")

        request = _StubRequest()

        async def _build_downloads() -> dict[str, Any] | None:
            page = await downloads_service.list_downloads_async(
                limit=20,
                offset=0,
                include_all=False,
                status_filter=None,
            )
            context = build_downloads_fragment_context(
                request,
                page=page,
                csrf_token="token",
                status_filter=None,
                include_all=False,
            )
            fragment = context["fragment"]
            template = templates.get_template("partials/downloads_table.j2")
            html = template.render(**context)
            return {
                "event": "downloads",
                "fragment_id": fragment.identifier,
                "html": html,
                "data_attributes": dict(fragment.data_attributes),
            }

        builder = _LiveFragmentBuilder(name="downloads", interval=0.1, build=_build_downloads)
        stream = _ui_event_stream(request, [builder])
        chunk = None
        try:
            async for chunk in stream:
                break
        finally:
            db_session.close()

        assert chunk is not None
        assert "event: fragment" in chunk
        assert "hx-downloads-table" in chunk
        assert '"html"' in chunk


def test_ui_events_stream_contains_fragment_markup(monkeypatch) -> None:
    class _StubDownloadsService:
        async def list_downloads_async(
            self,
            *,
            limit: int,
            offset: int,
            include_all: bool,
            status_filter: str | None,
        ) -> DownloadPage:
            return DownloadPage(
                items=(),
                limit=limit,
                offset=offset,
                has_next=False,
                has_previous=False,
            )

    class _StubJobsService:
        async def list_jobs(self, request: Any) -> tuple[Any, ...]:
            return ()

    class _StubWatchlistService:
        def __init__(self) -> None:
            self.async_calls: list[str] = []

        def list_entries(self, request: Any) -> WatchlistTable:
            raise AssertionError("synchronous list_entries should not be used")

        async def list_entries_async(self, request: Any) -> WatchlistTable:
            self.async_calls.append("list")
            await asyncio.sleep(0)
            return WatchlistTable(entries=())

    class _StubActivityService:
        def __init__(self) -> None:
            self.async_calls: list[tuple[int, int, str | None, str | None]] = []

        def list_activity(
            self,
            *,
            limit: int,
            offset: int,
            type_filter: str | None,
            status_filter: str | None,
        ) -> ActivityPage:
            raise AssertionError("synchronous list_activity should not be used")

        async def list_activity_async(
            self,
            *,
            limit: int,
            offset: int,
            type_filter: str | None,
            status_filter: str | None,
        ) -> ActivityPage:
            self.async_calls.append((limit, offset, type_filter, status_filter))
            await asyncio.sleep(0)
            return ActivityPage(
                items=(),
                limit=limit,
                offset=offset,
                total_count=0,
                type_filter=type_filter,
                status_filter=status_filter,
            )

    watchlist_stub = _StubWatchlistService()
    activity_stub = _StubActivityService()
    overrides = {
        get_downloads_ui_service: lambda: _StubDownloadsService(),
        get_jobs_ui_service: lambda: _StubJobsService(),
        get_watchlist_ui_service: lambda: watchlist_stub,
        get_activity_ui_service: lambda: activity_stub,
    }

    captured_payloads: list[dict[str, Any]] = []

    async def _capture_stream(request: Any, builders: list[_LiveFragmentBuilder]):
        for builder in builders:
            payload = await builder.build()
            if not payload:
                continue
            captured_payloads.append(payload)
            data = json.dumps(payload, ensure_ascii=False)
            yield f"event: fragment\ndata: {data}\n\n"

    monkeypatch.setattr("app.ui.routes.events._ui_event_stream", _capture_stream)

    with _create_client(monkeypatch, extra_env={"UI_LIVE_UPDATES": "SSE"}) as client:
        try:
            client.app.dependency_overrides.update(overrides)
            _login(client)
            headers = {"Cookie": _cookies_header(client)}
            response = client.get("/ui/events", headers=headers)
            assert response.status_code == 200
            body = response.text
            assert "event: fragment" in body
            assert "data:" in body
        finally:
            client.app.dependency_overrides.clear()

    assert captured_payloads, "expected at least one SSE payload"
    payload = captured_payloads[0]
    html = payload.get("html")
    assert isinstance(html, str)
    fragment_id = payload.get("fragment_id")
    assert isinstance(fragment_id, str)
    assert html.strip().startswith("<")
    assert fragment_id in html
    assert "<div" in html
    assert "list" in watchlist_stub.async_calls
    assert activity_stub.async_calls, "expected async list_activity to be invoked"
