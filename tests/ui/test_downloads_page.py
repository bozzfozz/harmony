from __future__ import annotations

from fastapi import status
from fastapi.responses import PlainTextResponse
import pytest

from app.db import get_session, init_db, session_scope
from app.dependencies import get_download_service
from app.errors import AppError, ErrorCode
from app.main import app
from app.models import Download
from app.services.download_service import DownloadService
from app.ui.services import DownloadPage, DownloadRow, get_downloads_ui_service
from tests.ui.test_fragments import (
    _RecordingDownloadsService,
    _csrf_headers,
    _login,
)
from tests.ui.test_ui_auth import _assert_html_response, _create_client


@pytest.fixture()
def _downloads_stub() -> _RecordingDownloadsService:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=1,
                filename="alpha.flac",
                status="failed",
                progress=0.5,
                priority=3,
                username="dj",
                created_at=None,
                updated_at=None,
            ),
        ],
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    return _RecordingDownloadsService(page)


def _override_downloads(stub: _RecordingDownloadsService) -> None:
    app.dependency_overrides[get_downloads_ui_service] = lambda: stub


def _reset_downloads_override() -> None:
    app.dependency_overrides.pop(get_downloads_ui_service, None)


def test_downloads_table_real_service(monkeypatch) -> None:
    init_db()
    with session_scope() as session:
        record = Download(
            filename="omega.flac",
            state="queued",
            progress=0.25,
            priority=2,
            username="dj",
        )
        session.add(record)
        session.flush()
        download_id = record.id

    class _StubTransfersApi:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def get_download_queue(self, identifier: int) -> dict[str, object]:
            self.calls.append(identifier)
            return {"status": "queued", "download_id": identifier}

    transfers = _StubTransfersApi()

    async def _override_get_download_service():
        db_session = get_session()

        async def _runner(func):
            return func(db_session)

        service = DownloadService(
            session=db_session,
            session_runner=_runner,
            transfers=transfers,
        )
        try:
            yield service
        finally:
            db_session.close()

    app.dependency_overrides[get_download_service] = _override_get_download_service

    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.get("/ui/downloads/table", headers=headers)
            _assert_html_response(response)
            assert "omega.flac" in response.text
    finally:
        app.dependency_overrides.pop(get_download_service, None)

    assert transfers.calls == [download_id]


def test_downloads_priority_update_success(
    monkeypatch, _downloads_stub: _RecordingDownloadsService
) -> None:
    _override_downloads(_downloads_stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/downloads/1/priority",
                data={"priority": "7", "csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response)
            html = response.text
            assert "alpha.flac" in html
            assert 'data-test="download-priority-input-1"' in html
            assert _downloads_stub.updated == [(1, 7)]
    finally:
        _reset_downloads_override()


def test_downloads_retry_success(monkeypatch, _downloads_stub: _RecordingDownloadsService) -> None:
    _override_downloads(_downloads_stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/downloads/1/retry",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response)
            html = response.text
            assert 'data-test="download-retry-1"' in html
            assert _downloads_stub.retried == [1]
    finally:
        _reset_downloads_override()


def test_downloads_retry_app_error(
    monkeypatch, _downloads_stub: _RecordingDownloadsService
) -> None:
    _downloads_stub.retry_exception = AppError(
        "Unable to retry download.",
        code=ErrorCode.DEPENDENCY_ERROR,
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
    _override_downloads(_downloads_stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/downloads/1/retry",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
            assert "Unable to retry download." in response.text
    finally:
        _reset_downloads_override()


def test_downloads_cancel_success(monkeypatch) -> None:
    page = DownloadPage(
        items=[
            DownloadRow(
                identifier=2,
                filename="beta.flac",
                status="queued",
                progress=0.0,
                priority=1,
                username=None,
                created_at=None,
                updated_at=None,
            ),
        ],
        limit=20,
        offset=0,
        has_next=False,
        has_previous=False,
    )
    stub = _RecordingDownloadsService(page)
    _override_downloads(stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.request(
                "DELETE",
                "/ui/downloads/2",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response)
            html = response.text
            assert "beta.flac" not in html
            assert stub.cancelled == [2]
    finally:
        _reset_downloads_override()


def test_downloads_cancel_app_error(
    monkeypatch, _downloads_stub: _RecordingDownloadsService
) -> None:
    _downloads_stub.cancel_exception = AppError(
        "Cancellation failed.",
        code=ErrorCode.VALIDATION_ERROR,
        http_status=status.HTTP_409_CONFLICT,
    )
    _override_downloads(_downloads_stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.request(
                "DELETE",
                "/ui/downloads/1",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            _assert_html_response(response, status_code=status.HTTP_409_CONFLICT)
            assert "Cancellation failed." in response.text
    finally:
        _reset_downloads_override()


def test_downloads_export_success(monkeypatch, _downloads_stub: _RecordingDownloadsService) -> None:
    _downloads_stub.export_response = PlainTextResponse(
        "id,filename\n1,alpha.flac\n",
        media_type="text/csv",
    )
    _override_downloads(_downloads_stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/downloads/export",
                data={"csrftoken": headers["X-CSRF-Token"], "format": "csv"},
                headers=headers,
            )
            assert response.status_code == status.HTTP_200_OK
            assert response.headers["content-type"].startswith("text/csv")
            assert 'attachment; filename="downloads.csv"' in response.headers.get(
                "content-disposition", ""
            )
            assert _downloads_stub.export_calls == [
                {"format": "csv", "status_filter": None, "from": None, "to": None}
            ]
    finally:
        _reset_downloads_override()


def test_downloads_export_app_error(
    monkeypatch, _downloads_stub: _RecordingDownloadsService
) -> None:
    _downloads_stub.export_exception = AppError(
        "Export unavailable.",
        code=ErrorCode.DEPENDENCY_ERROR,
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
    _override_downloads(_downloads_stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            headers = _csrf_headers(client)
            response = client.post(
                "/ui/downloads/export",
                data={"csrftoken": headers["X-CSRF-Token"]},
                headers=headers,
            )
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert "Export unavailable." in response.text
    finally:
        _reset_downloads_override()
