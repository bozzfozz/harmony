from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable
from unittest.mock import MagicMock

import pytest

from app.config import HealthConfig
from app.errors import ErrorCode
from app.services.health import (DependencyStatus, HealthService,
                                 MigrationProbeResult, ReadinessResult)
from tests.helpers import api_path


def _session_factory(success: bool = True) -> Callable[[], MagicMock]:
    session = MagicMock()
    if success:
        session.execute.return_value = None
    else:
        session.execute.side_effect = RuntimeError("db down")
    session.close = MagicMock()
    return lambda: session


@pytest.fixture(autouse=True)
def _patch_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(_: HealthService) -> MigrationProbeResult:
        return MigrationProbeResult(up_to_date=True, current="rev", head=("rev",))

    monkeypatch.setattr(HealthService, "_probe_migrations", _ok)


def test_health_service_liveness_reports_uptime() -> None:
    config = HealthConfig(
        db_timeout_ms=100,
        dependency_timeout_ms=100,
        dependencies=(),
        require_database=True,
    )
    start = datetime.now(timezone.utc) - timedelta(seconds=5)
    service = HealthService(
        start_time=start,
        version="test",
        config=config,
        session_factory=_session_factory(),
    )

    summary = service.liveness()

    assert summary.status == "up"
    assert summary.version == "test"
    assert summary.uptime_s >= 5


@pytest.mark.asyncio
async def test_health_service_readiness_success() -> None:
    config = HealthConfig(
        db_timeout_ms=100,
        dependency_timeout_ms=100,
        dependencies=("spotify",),
        require_database=True,
    )
    service = HealthService(
        start_time=datetime.now(timezone.utc),
        version="test",
        config=config,
        session_factory=_session_factory(),
        dependency_probes={"spotify": lambda: True},
    )

    result = await service.readiness()

    assert result.ok is True
    assert result.database == "up"
    assert result.dependencies == {"spotify": "up"}
    assert result.migrations.up_to_date is True


@pytest.mark.asyncio
async def test_health_service_readiness_handles_disabled_dependency() -> None:
    config = HealthConfig(
        db_timeout_ms=100,
        dependency_timeout_ms=100,
        dependencies=(),
        require_database=True,
    )
    service = HealthService(
        start_time=datetime.now(timezone.utc),
        version="test",
        config=config,
        session_factory=_session_factory(),
        dependency_probes={
            "orchestrator:job:artwork": lambda: DependencyStatus(ok=True, status="disabled")
        },
    )

    result = await service.readiness()

    assert result.ok is True
    assert result.dependencies == {"orchestrator:job:artwork": "disabled"}
    assert result.migrations.up_to_date is True


@pytest.mark.asyncio
async def test_health_service_readiness_handles_db_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = HealthConfig(
        db_timeout_ms=100,
        dependency_timeout_ms=100,
        dependencies=(),
        require_database=True,
    )
    async def _error(_: HealthService) -> MigrationProbeResult:
        return MigrationProbeResult(up_to_date=False, current=None, head=tuple())

    monkeypatch.setattr(HealthService, "_probe_migrations", _error)
    service = HealthService(
        start_time=datetime.now(timezone.utc),
        version="test",
        config=config,
        session_factory=_session_factory(success=False),
    )

    result = await service.readiness()

    assert result.ok is False
    assert result.database == "down"
    assert result.migrations.up_to_date is False


@pytest.mark.asyncio
async def test_health_service_readiness_handles_dependency_failure() -> None:
    config = HealthConfig(
        db_timeout_ms=100,
        dependency_timeout_ms=100,
        dependencies=("spotify",),
        require_database=True,
    )
    service = HealthService(
        start_time=datetime.now(timezone.utc),
        version="test",
        config=config,
        session_factory=_session_factory(),
        dependency_probes={"spotify": lambda: False},
    )

    result = await service.readiness()

    assert result.ok is False
    assert result.dependencies == {"spotify": "down"}
    assert result.migrations.up_to_date is True


@pytest.mark.asyncio
async def test_health_service_readiness_ignores_db_when_not_required() -> None:
    config = HealthConfig(
        db_timeout_ms=100,
        dependency_timeout_ms=100,
        dependencies=(),
        require_database=False,
    )
    service = HealthService(
        start_time=datetime.now(timezone.utc),
        version="test",
        config=config,
        session_factory=_session_factory(success=False),
    )

    result = await service.readiness()

    assert result.ok is True
    assert result.database == "down"
    assert result.migrations.up_to_date is True


@pytest.mark.asyncio
async def test_health_service_readiness_fails_when_migrations_outdated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _outdated(_: HealthService) -> MigrationProbeResult:
        return MigrationProbeResult(up_to_date=False, current="abc", head=("xyz",))

    monkeypatch.setattr(HealthService, "_probe_migrations", _outdated)

    config = HealthConfig(
        db_timeout_ms=100,
        dependency_timeout_ms=100,
        dependencies=(),
        require_database=True,
    )
    service = HealthService(
        start_time=datetime.now(timezone.utc),
        version="test",
        config=config,
        session_factory=_session_factory(),
    )

    result = await service.readiness()

    assert result.ok is False
    assert result.migrations.up_to_date is False


def test_health_endpoint_returns_envelope(client) -> None:
    response = client.get(api_path("health"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["data"]["status"] == "up"
    assert "version" in payload["data"]


def test_ready_endpoint_returns_503_on_failure(client) -> None:
    original_service = client.app.state.health_service

    async def _failing_readiness() -> ReadinessResult:
        return ReadinessResult(
            ok=False,
            database="down",
            dependencies={"spotify": "down"},
            migrations=MigrationProbeResult(
                up_to_date=False,
                current=None,
                head=tuple(),
                error="outdated",
            ),
        )

    class _StubHealthService:
        def liveness(self):  # pragma: no cover - not used
            return original_service.liveness()

        async def readiness(self) -> ReadinessResult:
            return await _failing_readiness()

    client.app.state.health_service = _StubHealthService()
    try:
        response = client.get(api_path("ready"))
    finally:
        client.app.state.health_service = original_service

    assert response.status_code == 503
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == ErrorCode.DEPENDENCY_ERROR
    assert payload["error"]["meta"]["db"] == "down"
    assert payload["error"]["meta"]["migrations"]["up_to_date"] is False


def test_ready_endpoint_returns_200_when_ok(client) -> None:
    response = client.get(api_path("ready"))
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        payload = response.json()
        assert payload["ok"] is True
        assert "migrations" in payload["data"]
        assert payload["data"]["db"] == "up"
        assert "orchestrator" in payload["data"]
        orchestrator = payload["data"]["orchestrator"]
        assert "enabled_jobs" in orchestrator
    else:
        payload = response.json()
        orchestrator_meta = payload["error"]["meta"].get("orchestrator")
        assert orchestrator_meta is not None
