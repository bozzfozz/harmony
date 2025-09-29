from __future__ import annotations

import asyncio

import pytest

from app.main import _stop_background_workers, app
from tests.fixtures.worker_stubs import WorkerRegistry
from tests.support.async_utils import wait_for_event

pytest_plugins = ["tests.fixtures.worker_stubs"]


pytestmark = [pytest.mark.usefixtures("lifespan_worker_settings")]


@pytest.mark.asyncio
@pytest.mark.lifespan_workers
async def test_lifespan_happy_path_starts_and_stops_workers(
    worker_registry: WorkerRegistry,
) -> None:
    async with app.router.lifespan_context(app):
        pass

    for worker in worker_registry.all_workers():
        assert worker.started is True
        assert worker.stopped is True
        assert worker.start_calls == 1
        assert worker.stop_calls == 1

    start_events = [
        event for event in worker_registry.log_events if event.get("event") == "worker.start"
    ]
    stop_events = [
        event for event in worker_registry.log_events if event.get("event") == "worker.stop"
    ]
    assert start_events and stop_events
    assert {event["status"] for event in start_events} == {"ok"}
    assert {event["status"] for event in stop_events} == {"ok"}
    assert all("duration_ms" in event for event in start_events)
    assert all("duration_ms" in event for event in stop_events)


@pytest.mark.asyncio
@pytest.mark.lifespan_workers
async def test_lifespan_start_failure_rolls_back_and_logs_error(
    worker_registry: WorkerRegistry,
) -> None:
    worker_registry.scenarios["metadata"].fail_on_start = True
    ctx = app.router.lifespan_context(app)
    with pytest.raises(RuntimeError):
        await ctx.__aenter__()

    error_events = [
        event
        for event in worker_registry.log_events
        if event.get("event") == "worker.start" and event.get("status") == "error"
    ]
    assert error_events

    started_workers = [worker for worker in worker_registry.all_workers() if worker.started]
    assert started_workers  # sanity check that some workers initialised before the failure

    # Clean up manually because the lifespan never yielded control.
    await _stop_background_workers(app)

    for worker in started_workers:
        assert worker.stop_calls >= 1


@pytest.mark.asyncio
@pytest.mark.lifespan_workers
async def test_lifespan_double_start_is_idempotent(worker_registry: WorkerRegistry) -> None:
    async with app.router.lifespan_context(app):
        pass

    first_generation = {name: list(workers) for name, workers in worker_registry.instances.items()}

    async with app.router.lifespan_context(app):
        pass

    for name, workers in worker_registry.instances.items():
        assert len(workers) == len(first_generation[name]) * 2
        for worker in workers:
            assert worker.start_calls == 1
            assert worker.stop_calls == 1


@pytest.mark.asyncio
@pytest.mark.lifespan_workers
async def test_lifespan_double_stop_is_idempotent(worker_registry: WorkerRegistry) -> None:
    async with app.router.lifespan_context(app):
        pass

    baseline = {worker: worker.stop_calls for worker in worker_registry.all_workers()}
    await _stop_background_workers(app)

    for worker, previous_count in baseline.items():
        assert worker.stop_calls == previous_count


@pytest.mark.asyncio
@pytest.mark.lifespan_workers
async def test_worker_cancel_on_shutdown_finishes_within_grace(
    worker_registry: WorkerRegistry,
) -> None:
    scenario = worker_registry.scenarios["sync"]
    scenario.run_forever = True
    scenario.stop_timeout = 0.3

    async with app.router.lifespan_context(app):
        assert worker_registry.instances["sync"]
        sync_worker = worker_registry.instances["sync"][0]
        assert await wait_for_event(sync_worker.background_started, timeout=0.2)

    sync_worker = worker_registry.instances["sync"][0]
    assert sync_worker.background_finished.is_set()
    assert sync_worker.stop_calls == 1
    assert sync_worker.stop_durations[-1] <= scenario.stop_timeout * 1_000 + 50


@pytest.mark.asyncio
@pytest.mark.lifespan_workers
async def test_worker_start_timeout_is_surface_as_timeout(worker_registry: WorkerRegistry) -> None:
    worker_registry.scenarios["matching"].start_delay = 1.0

    ctx = app.router.lifespan_context(app)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ctx.__aenter__(), timeout=0.05)

    await ctx.__aexit__(None, None, None)
    await _stop_background_workers(app)


@pytest.mark.asyncio
@pytest.mark.lifespan_workers
async def test_worker_background_crash_is_logged(worker_registry: WorkerRegistry) -> None:
    scenario = worker_registry.scenarios["playlist_sync"]
    scenario.run_forever = True
    scenario.crash_during_run = True
    scenario.crash_delay = 0.01

    async with app.router.lifespan_context(app):
        assert worker_registry.instances["playlist_sync"]
        worker = worker_registry.instances["playlist_sync"][0]
        assert await wait_for_event(worker.background_finished, timeout=0.2)

    worker = worker_registry.instances["playlist_sync"][0]
    assert worker.background_error is not None

    error_logs = [
        event
        for event in worker_registry.log_events
        if event.get("event") == "worker.run" and event.get("status") == "error"
    ]
    assert error_logs
