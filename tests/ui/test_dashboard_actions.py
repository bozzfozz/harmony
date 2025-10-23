from __future__ import annotations

import logging
from typing import Any

from fastapi import status
from fastapi.testclient import TestClient
import pytest

from app.config import override_runtime_env
from app.dependencies import get_app_config
from app.errors import AppError, ErrorCode
from app.main import app
from app.ui.services import SyncActionResult, get_sync_ui_service
from app.utils import metrics


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - simple collector
        self.records.append(record)


def _cookies_header(client: TestClient) -> str:
    return "; ".join(f"{name}={value}" for name, value in client.cookies.items())


def _create_client(monkeypatch, extra_env: dict[str, str] | None = None) -> TestClient:
    monkeypatch.setenv("HARMONY_API_KEYS", "primary-key")
    monkeypatch.setenv("UI_ROLE_DEFAULT", "operator")
    monkeypatch.setenv("UI_ROLE_OVERRIDES", "")
    monkeypatch.setenv("UI_FEATURE_SPOTIFY", "true")
    monkeypatch.setenv("UI_FEATURE_SOULSEEK", "true")
    monkeypatch.setenv("UI_FEATURE_DLQ", "true")
    monkeypatch.setenv("UI_FEATURE_IMPORTS", "true")
    if extra_env:
        for key, value in extra_env.items():
            monkeypatch.setenv(key, value)
    override_runtime_env(None)
    get_app_config.cache_clear()
    config = get_app_config()
    assert config.security.api_keys
    metrics.reset_registry()
    return TestClient(app)


def _login(client: TestClient) -> str:
    response = client.post(
        "/ui/login",
        data={"api_key": "primary-key"},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    token = client.cookies.get("csrftoken")
    assert token
    if token.startswith('"') and token.endswith('"'):
        token = token[1:-1]
    return token


@pytest.fixture
def _sync_dependency_override():
    original = app.dependency_overrides.get(get_sync_ui_service)
    try:
        yield
    finally:
        if original is not None:
            app.dependency_overrides[get_sync_ui_service] = original
        else:
            app.dependency_overrides.pop(get_sync_ui_service, None)


def test_dashboard_sync_action_success(monkeypatch, _sync_dependency_override) -> None:
    with _create_client(monkeypatch) as client:

        class StubSyncService:
            async def trigger_manual_sync(self, request) -> SyncActionResult:
                return SyncActionResult(
                    message="Manual sync triggered",
                    status_code=status.HTTP_202_ACCEPTED,
                    results={"playlists": "completed"},
                    errors={"library_scan": "Library scan disabled"},
                    counters={"tracks_synced": 5, "errors": 1},
                )

        app.dependency_overrides[get_sync_ui_service] = lambda: StubSyncService()
        csrf_token = _login(client)
        logger = logging.getLogger("app.ui.router")
        handler = _RecordingHandler()
        logger.addHandler(handler)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            response = client.post(
                "/ui/dashboard/sync",
                headers={
                    "Cookie": _cookies_header(client),
                    "X-CSRF-Token": csrf_token,
                    "HX-Request": "true",
                },
            )
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

    assert response.status_code == status.HTTP_200_OK
    html = response.text
    assert "Manual sync triggered" in html
    assert 'hx-swap-oob="outerHTML"' in html
    assert 'data-test="dashboard-sync-result-playlists"' in html
    assert 'data-test="dashboard-sync-metric-tracks-synced"' in html
    assert "dashboard-sync-status" in html

    events = [
        record
        for record in handler.records
        if getattr(record, "event", None) == "ui.action.dashboard_sync"
    ]
    assert events, "expected sync action log event"
    success_event = events[-1]
    assert getattr(success_event, "status", None) == "success"
    assert getattr(success_event, "results", None) == 1
    assert getattr(success_event, "errors", None) == 1


def test_dashboard_sync_action_failure(monkeypatch, _sync_dependency_override) -> None:
    with _create_client(monkeypatch) as client:

        class FailingSyncService:
            async def trigger_manual_sync(self, request) -> SyncActionResult:
                raise AppError(
                    "Sync blocked",
                    code=ErrorCode.DEPENDENCY_ERROR,
                    http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    meta={"missing": {"spotify": ["client_secret"]}},
                )

        app.dependency_overrides[get_sync_ui_service] = lambda: FailingSyncService()
        csrf_token = _login(client)
        logger = logging.getLogger("app.ui.router")
        handler = _RecordingHandler()
        logger.addHandler(handler)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            response = client.post(
                "/ui/dashboard/sync",
                headers={
                    "Cookie": _cookies_header(client),
                    "X-CSRF-Token": csrf_token,
                    "HX-Request": "true",
                },
            )
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

    assert response.status_code == status.HTTP_200_OK
    html = response.text
    assert "Sync blocked" in html
    assert 'hx-swap-oob="outerHTML"' in html
    assert "missing client_secret" in html.lower()

    events = [
        record
        for record in handler.records
        if getattr(record, "event", None) == "ui.action.dashboard_sync"
    ]
    assert events, "expected sync action error log"
    error_event = events[-1]
    assert getattr(error_event, "status", None) == "error"
    assert getattr(error_event, "error", None) in {
        ErrorCode.DEPENDENCY_ERROR,
        ErrorCode.DEPENDENCY_ERROR.value,
    }
