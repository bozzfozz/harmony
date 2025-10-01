from __future__ import annotations

import inspect

import app.orchestrator.dispatcher as dispatcher
import app.orchestrator.scheduler as scheduler
import app.orchestrator.timer as timer


def _assert_no_env_lookup(module) -> None:
    source = inspect.getsource(module)
    assert "os.getenv" not in source


def test_scheduler_relies_on_settings() -> None:
    _assert_no_env_lookup(scheduler)


def test_dispatcher_relies_on_settings() -> None:
    _assert_no_env_lookup(dispatcher)


def test_timer_relies_on_settings() -> None:
    _assert_no_env_lookup(timer)
