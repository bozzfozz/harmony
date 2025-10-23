from __future__ import annotations

import pytest
from datetime import datetime

from fastapi import status

from app.errors import AppError, ErrorCode
from app.main import app
from app.ui.services import get_watchlist_ui_service
from app.ui.services.watchlist import WatchlistRow
from tests.ui.test_fragments import _StubWatchlistService, _csrf_headers, _login
from tests.ui.test_ui_auth import _assert_html_response, _create_client


@pytest.fixture
def _watchlist_stub() -> _StubWatchlistService:
    return _StubWatchlistService(
        entries=(
            WatchlistRow(
                artist_key="spotify:artist:stub",
                priority=3,
                state_key="watchlist.state.active",
            ),
        )
    )


def _override_watchlist(stub: _StubWatchlistService) -> None:
    app.dependency_overrides[get_watchlist_ui_service] = lambda: stub


def _reset_watchlist_override() -> None:
    app.dependency_overrides.pop(get_watchlist_ui_service, None)


def test_watchlist_pause_success(monkeypatch, _watchlist_stub: _StubWatchlistService) -> None:
    _override_watchlist(_watchlist_stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/watchlist/spotify:artist:stub/pause",
                data={
                    "limit": "25",
                    "offset": "5",
                    "reason": "Maintenance window",
                    "resume_at": "2024-05-01T09:30",
                },
                headers=_csrf_headers(client),
            )
            _assert_html_response(response)
            html = response.text
            assert "Paused" in html
            assert 'data-test="watchlist-resume-spotify-artist-stub"' in html
            assert _watchlist_stub.paused == ["spotify:artist:stub"]
            assert _watchlist_stub.pause_payloads == [
                ("Maintenance window", datetime.fromisoformat("2024-05-01T09:30"))
            ]
            assert "pause" in _watchlist_stub.async_calls
    finally:
        _reset_watchlist_override()


def test_watchlist_pause_app_error(monkeypatch, _watchlist_stub: _StubWatchlistService) -> None:
    _watchlist_stub.pause_exception = AppError(
        "Unable to pause entry.",
        code=ErrorCode.DEPENDENCY_ERROR,
        http_status=status.HTTP_502_BAD_GATEWAY,
    )
    _override_watchlist(_watchlist_stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/watchlist/spotify:artist:stub/pause",
                data={"reason": "Investigation"},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response, status_code=status.HTTP_502_BAD_GATEWAY)
            assert "Unable to pause entry." in response.text
            assert _watchlist_stub.pause_payloads == [("Investigation", None)]
            assert "pause" in _watchlist_stub.async_calls
    finally:
        _reset_watchlist_override()


def test_watchlist_pause_invalid_resume(
    monkeypatch, _watchlist_stub: _StubWatchlistService
) -> None:
    _override_watchlist(_watchlist_stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/watchlist/spotify:artist:stub/pause",
                data={"resume_at": "invalid-date"},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response, status_code=status.HTTP_400_BAD_REQUEST)
            assert "Please provide a valid resume date and time." in response.text
            assert _watchlist_stub.pause_payloads == []
            assert "pause" not in _watchlist_stub.async_calls
    finally:
        _reset_watchlist_override()


def test_watchlist_resume_success(monkeypatch) -> None:
    stub = _StubWatchlistService(
        entries=(
            WatchlistRow(
                artist_key="spotify:artist:paused",
                priority=4,
                state_key="watchlist.state.paused",
                paused=True,
            ),
        )
    )
    _override_watchlist(stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/watchlist/spotify:artist:paused/resume",
                data={"limit": "10"},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response)
            html = response.text
            assert "Active" in html
            assert 'data-test="watchlist-pause-spotify-artist-paused"' in html
            assert stub.resumed == ["spotify:artist:paused"]
            assert "resume" in stub.async_calls
    finally:
        _reset_watchlist_override()


def test_watchlist_resume_app_error(monkeypatch) -> None:
    stub = _StubWatchlistService()
    stub.resume_exception = AppError(
        "Unable to resume entry.",
        code=ErrorCode.DEPENDENCY_ERROR,
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
    _override_watchlist(stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/watchlist/spotify:artist:stub/resume",
                data={},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
            assert "Unable to resume entry." in response.text
            assert "resume" in stub.async_calls
    finally:
        _reset_watchlist_override()


def test_watchlist_delete_success(monkeypatch) -> None:
    stub = _StubWatchlistService(
        entries=(
            WatchlistRow(
                artist_key="spotify:artist:delete",
                priority=2,
                state_key="watchlist.state.active",
            ),
            WatchlistRow(
                artist_key="spotify:artist:keep",
                priority=5,
                state_key="watchlist.state.active",
            ),
        )
    )
    _override_watchlist(stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/watchlist/spotify:artist:delete/delete",
                data={},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response)
            html = response.text
            assert "spotify:artist:delete" not in html
            assert "spotify:artist:keep" in html
            assert stub.deleted == ["spotify:artist:delete"]
            assert "delete" in stub.async_calls
    finally:
        _reset_watchlist_override()


def test_watchlist_delete_app_error(monkeypatch) -> None:
    stub = _StubWatchlistService()
    stub.delete_exception = AppError(
        "Unable to delete entry.",
        code=ErrorCode.DEPENDENCY_ERROR,
        http_status=status.HTTP_502_BAD_GATEWAY,
    )
    _override_watchlist(stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/watchlist/spotify:artist:stub/delete",
                data={},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response, status_code=status.HTTP_502_BAD_GATEWAY)
            assert "Unable to delete entry." in response.text
            assert "delete" in stub.async_calls
    finally:
        _reset_watchlist_override()


def test_watchlist_priority_app_error(monkeypatch) -> None:
    stub = _StubWatchlistService()
    stub.update_exception = AppError(
        "Priority update failed.",
        code=ErrorCode.DEPENDENCY_ERROR,
        http_status=status.HTTP_409_CONFLICT,
    )
    _override_watchlist(stub)
    try:
        with _create_client(monkeypatch) as client:
            _login(client)
            response = client.post(
                "/ui/watchlist/spotify:artist:stub/priority",
                data={"priority": "10"},
                headers=_csrf_headers(client),
            )
            _assert_html_response(response, status_code=status.HTTP_409_CONFLICT)
            assert "Priority update failed." in response.text
            assert "update" in stub.async_calls
    finally:
        _reset_watchlist_override()
