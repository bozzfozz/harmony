"""Tests for :mod:`app.services.health` dependency status normalisation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import pytest

from app.config import HealthConfig
from app.services.health import DependencyStatus, HealthService


class _StubSession:
    def close(self) -> None:
        pass


def _build_service(probes: Mapping[str, Callable[[], object]]) -> HealthService:
    config = HealthConfig(
        db_timeout_ms=100,
        dependency_timeout_ms=100,
        dependencies=(),
        require_database=False,
    )
    return HealthService(
        start_time=datetime.now(UTC),
        version="test",
        config=config,
        session_factory=lambda: _StubSession(),
        dependency_probes=probes,
    )


@pytest.mark.parametrize(
    "value, expected",
    [
        (
            DependencyStatus(ok=True, status=" Ready "),
            DependencyStatus(ok=True, status="ready"),
        ),
        (
            DependencyStatus(ok=False, status="  "),
            DependencyStatus(ok=False, status="down"),
        ),
        (
            DependencyStatus(ok=True, status=""),
            DependencyStatus(ok=True, status="up"),
        ),
    ],
)
def test_normalise_dependency_status_existing_objects(
    value: DependencyStatus, expected: DependencyStatus
) -> None:
    """Existing :class:`DependencyStatus` instances are normalised consistently."""

    normalised = HealthService._normalise_dependency_status(value)

    assert normalised == expected


@pytest.mark.asyncio
async def test_probe_dependency_handles_async_probe() -> None:
    async def async_probe() -> DependencyStatus:
        await asyncio.sleep(0)
        return DependencyStatus(ok=True, status="up")

    service = _build_service({"async": async_probe})

    status = await service._probe_dependency("async")

    assert status == DependencyStatus(ok=True, status="up")


@pytest.mark.asyncio
async def test_probe_dependency_logs_failure(caplog: pytest.LogCaptureFixture) -> None:
    def failing_probe() -> bool:
        raise RuntimeError("boom")

    service = _build_service({"failing": failing_probe})

    with caplog.at_level("WARNING"):
        status = await service._probe_dependency("failing")

    assert status == DependencyStatus(ok=False, status="down")
    assert any("Dependency probe failed" in message for message in caplog.messages)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("up", DependencyStatus(ok=True, status="up")),
        (" disabled ", DependencyStatus(ok=True, status="disabled")),
        ("error", DependencyStatus(ok=False, status="error")),
        ("   ", DependencyStatus(ok=False, status="down")),
    ],
)
def test_normalise_dependency_status_strings(value: str, expected: DependencyStatus) -> None:
    """String inputs are mapped onto standardised dependency status results."""

    normalised = HealthService._normalise_dependency_status(value)

    assert normalised == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (True, DependencyStatus(ok=True, status="up")),
        (False, DependencyStatus(ok=False, status="down")),
        (1, DependencyStatus(ok=True, status="up")),
        (0, DependencyStatus(ok=False, status="down")),
    ],
)
def test_normalise_dependency_status_truthy_values(
    value: bool | int, expected: DependencyStatus
) -> None:
    """Non-string, non-status inputs rely on their truthiness when normalising."""

    normalised = HealthService._normalise_dependency_status(value)

    assert normalised == expected
