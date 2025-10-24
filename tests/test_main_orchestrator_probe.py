"""Tests for the _orchestrator_component_probe helper."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.main import _orchestrator_component_probe, app
from app.services.health import DependencyStatus


@pytest.fixture(autouse=True)
def restore_orchestrator_status() -> Iterator[None]:
    """Ensure orchestrator status on the global FastAPI app is restored."""

    original = getattr(app.state, "orchestrator_status", None)
    has_original = hasattr(app.state, "orchestrator_status")
    try:
        yield
    finally:
        if not has_original and hasattr(app.state, "orchestrator_status"):
            delattr(app.state, "orchestrator_status")
        else:
            app.state.orchestrator_status = original


@pytest.mark.parametrize(
    ("component", "expected_key", "running_key"),
    [
        ("scheduler", "scheduler_expected", "scheduler_running"),
        ("dispatcher", "dispatcher_expected", "dispatcher_running"),
        ("watchlist_timer", "watchlist_timer_expected", "watchlist_timer_running"),
    ],
)
def test_probe_reports_up_when_component_running(
    component: str, expected_key: str, running_key: str
) -> None:
    app.state.orchestrator_status = {expected_key: True, running_key: True}

    status = _orchestrator_component_probe(component)()

    assert status == DependencyStatus(ok=True, status="up")


@pytest.mark.parametrize(
    ("component", "expected_key", "running_key"),
    [
        ("scheduler", "scheduler_expected", "scheduler_running"),
        ("dispatcher", "dispatcher_expected", "dispatcher_running"),
        ("watchlist_timer", "watchlist_timer_expected", "watchlist_timer_running"),
    ],
)
def test_probe_reports_disabled_when_component_not_expected(
    component: str, expected_key: str, running_key: str
) -> None:
    app.state.orchestrator_status = {expected_key: False, running_key: False}

    status = _orchestrator_component_probe(component)()

    assert status == DependencyStatus(ok=True, status="disabled")


@pytest.mark.parametrize(
    ("component", "expected_key", "running_key"),
    [
        ("scheduler", "scheduler_expected", "scheduler_running"),
        ("dispatcher", "dispatcher_expected", "dispatcher_running"),
        ("watchlist_timer", "watchlist_timer_expected", "watchlist_timer_running"),
    ],
)
def test_probe_reports_down_when_component_expected_but_not_running(
    component: str, expected_key: str, running_key: str
) -> None:
    app.state.orchestrator_status = {expected_key: True, running_key: False}

    status = _orchestrator_component_probe(component)()

    assert status == DependencyStatus(ok=False, status="down")


@pytest.mark.parametrize(
    "job_name",
    [
        "sync",
        "matching",
        "retry",
        "watchlist",
        "artist_sync",
    ],
)
@pytest.mark.parametrize("enabled", [True, False])
def test_probe_reports_job_enablement(job_name: str, enabled: bool) -> None:
    orchestrator_status: dict[str, Any] = {"enabled_jobs": {job_name: enabled}}
    app.state.orchestrator_status = orchestrator_status

    status = _orchestrator_component_probe(job_name)()

    expected_status = "enabled" if enabled else "disabled"
    assert status == DependencyStatus(ok=True, status=expected_status)


def test_probe_reports_unknown_for_untracked_job() -> None:
    app.state.orchestrator_status = {"enabled_jobs": {}}

    status = _orchestrator_component_probe("nonexistent-job")()

    assert status == DependencyStatus(ok=False, status="unknown")
