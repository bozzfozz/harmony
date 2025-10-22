from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.errors import AppError, ErrorCode
from app.main import app
from app.ui.context.dashboard import build_dashboard_page_context
from app.ui.context.common import KpiCard, SidebarSection
from app.ui.services import (
    DashboardConnectionStatus,
    DashboardHealthIssue,
    DashboardHealthSummary,
    DashboardStatusSummary,
    DashboardWorkerStatus,
    get_dashboard_ui_service,
)
from app.ui.session import UiFeatures, UiSession
from tests.ui.test_ui_auth import _assert_html_response, _create_client


class _StubDashboardService:
    def __init__(self) -> None:
        self.status_summary = DashboardStatusSummary(
            status="ok",
            version="1.2.3",
            uptime_seconds=3600.0,
            readiness_status="ready",
            connections=(
                DashboardConnectionStatus(name="database", status="up"),
                DashboardConnectionStatus(name="redis", status="degraded"),
            ),
            readiness_issues=(),
        )
        self.health_summary = DashboardHealthSummary(
            live_status="ok",
            ready_status="ok",
            ready_ok=True,
            checks={},
            issues=(DashboardHealthIssue(component="database", message="Connected"),),
        )
        self.worker_rows: tuple[DashboardWorkerStatus, ...] = (
            DashboardWorkerStatus(
                name="sync",
                status="running",
                queue_size=5,
                last_seen="2024-04-01T12:00:00",
                component=None,
                job="sync",
            ),
        )
        self.status_exc: Exception | None = None
        self.health_exc: Exception | None = None
        self.workers_exc: Exception | None = None

    async def fetch_status(self, request) -> DashboardStatusSummary:
        if self.status_exc is not None:
            raise self.status_exc
        return self.status_summary

    async def fetch_health(self, request) -> DashboardHealthSummary:
        if self.health_exc is not None:
            raise self.health_exc
        return self.health_summary

    async def fetch_workers(self, request) -> tuple[DashboardWorkerStatus, ...]:
        if self.workers_exc is not None:
            raise self.workers_exc
        return self.worker_rows


def _login(client: TestClient) -> dict[str, str]:
    response = client.post("/ui/login", data={"api_key": "primary-key"}, follow_redirects=False)
    assert response.status_code == 303
    cookies = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    assert cookies
    return {"Cookie": cookies}


@pytest.fixture()
def _stub_service() -> _StubDashboardService:
    return _StubDashboardService()


def test_dashboard_page_context_includes_async_fragments() -> None:
    request = type("_Request", (), {"url_for": lambda self, name: f"/ui/{name}"})()
    features = UiFeatures(spotify=True, soulseek=False, dlq=True, imports=True)
    session = UiSession(
        identifier="session",
        role="operator",
        features=features,
        fingerprint="fp",
        issued_at=_now(),
        last_seen_at=_now(),
    )
    context = build_dashboard_page_context(request, session=session, csrf_token="csrf-token")

    status_fragment = context["status_fragment"]
    health_fragment = context["health_fragment"]
    workers_fragment = context["workers_fragment"]

    assert status_fragment.poll_interval_seconds == 30
    assert status_fragment.swap == "innerHTML"
    assert health_fragment.poll_interval_seconds == 60
    assert workers_fragment.poll_interval_seconds == 45
    assert isinstance(context["kpi_cards"], tuple)
    assert all(isinstance(card, KpiCard) for card in context["kpi_cards"])
    assert isinstance(context["sidebar_sections"], tuple)
    assert all(isinstance(section, SidebarSection) for section in context["sidebar_sections"])


def test_dashboard_status_fragment_success(monkeypatch, _stub_service) -> None:
    with _client_with_service(monkeypatch, _stub_service) as client:
        headers = _login(client)
        response = client.get("/ui/dashboard/status", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert "database" in html
        assert "Version" in html


def test_dashboard_status_fragment_app_error(monkeypatch, _stub_service) -> None:
    _stub_service.status_exc = AppError("Service unavailable", code=ErrorCode.DEPENDENCY_ERROR)
    with _client_with_service(monkeypatch, _stub_service) as client:
        headers = _login(client)
        response = client.get("/ui/dashboard/status", headers=headers)
        _assert_html_response(response)
        assert "Service unavailable" in response.text
        assert "fragment-retry" in response.text


def test_dashboard_status_fragment_unexpected_error(monkeypatch, _stub_service) -> None:
    _stub_service.status_exc = RuntimeError("boom")
    with _client_with_service(monkeypatch, _stub_service) as client:
        headers = _login(client)
        response = client.get("/ui/dashboard/status", headers=headers)
        _assert_html_response(response, status_code=500)
        assert "Unable to load dashboard status." in response.text


def test_dashboard_health_fragment_success(monkeypatch, _stub_service) -> None:
    with _client_with_service(monkeypatch, _stub_service) as client:
        headers = _login(client)
        response = client.get("/ui/dashboard/health", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert "Liveness" in html
        assert "Health issues" in html


def test_dashboard_health_fragment_app_error(monkeypatch, _stub_service) -> None:
    _stub_service.health_exc = AppError("Health unavailable", code=ErrorCode.DEPENDENCY_ERROR)
    with _client_with_service(monkeypatch, _stub_service) as client:
        headers = _login(client)
        response = client.get("/ui/dashboard/health", headers=headers)
        _assert_html_response(response)
        assert "Health unavailable" in response.text


def test_dashboard_health_fragment_unexpected_error(monkeypatch, _stub_service) -> None:
    _stub_service.health_exc = RuntimeError("boom")
    with _client_with_service(monkeypatch, _stub_service) as client:
        headers = _login(client)
        response = client.get("/ui/dashboard/health", headers=headers)
        _assert_html_response(response, status_code=500)
        assert "Unable to load dashboard health information." in response.text


def test_dashboard_workers_fragment_success(monkeypatch, _stub_service) -> None:
    with _client_with_service(monkeypatch, _stub_service) as client:
        headers = _login(client)
        response = client.get("/ui/dashboard/workers", headers=headers)
        _assert_html_response(response)
        html = response.text
        assert "Queue size" in html
        assert "Status:" in html


def test_dashboard_workers_fragment_app_error(monkeypatch, _stub_service) -> None:
    _stub_service.workers_exc = AppError("Workers unavailable", code=ErrorCode.DEPENDENCY_ERROR)
    with _client_with_service(monkeypatch, _stub_service) as client:
        headers = _login(client)
        response = client.get("/ui/dashboard/workers", headers=headers)
        _assert_html_response(response)
        assert "Workers unavailable" in response.text


def test_dashboard_workers_fragment_unexpected_error(monkeypatch, _stub_service) -> None:
    _stub_service.workers_exc = RuntimeError("boom")
    with _client_with_service(monkeypatch, _stub_service) as client:
        headers = _login(client)
        response = client.get("/ui/dashboard/workers", headers=headers)
        _assert_html_response(response, status_code=500)
        assert "Unable to load worker information." in response.text


@contextmanager
def _client_with_service(monkeypatch, service: _StubDashboardService) -> TestClient:
    app.dependency_overrides[get_dashboard_ui_service] = lambda: service
    with _create_client(monkeypatch) as client:
        try:
            yield client
        finally:
            app.dependency_overrides.pop(get_dashboard_ui_service, None)


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(tz=UTC)
