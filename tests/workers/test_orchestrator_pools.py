"""Tests covering dispatcher pool concurrency controls."""

from __future__ import annotations

import asyncio
import random

import pytest

from app.orchestrator.dispatcher import Dispatcher


class _StubScheduler:
    def __init__(self, jobs: list) -> None:
        self._jobs = jobs
        self.poll_interval = 0.01

    def lease_ready_jobs(self):
        if not self._jobs:
            return []
        jobs, self._jobs = self._jobs, []
        return jobs

    def request_stop(self) -> None:  # pragma: no cover - compatibility shim
        self._jobs.clear()


@pytest.mark.asyncio
async def test_dispatcher_respects_pool_limits(
    queue_job_factory,
    stub_queue_persistence,
) -> None:
    jobs = [
        queue_job_factory(job_id=1, job_type="sync", lease_timeout_seconds=20),
        queue_job_factory(job_id=2, job_type="sync", lease_timeout_seconds=20),
    ]
    scheduler = _StubScheduler(jobs)
    max_running = 0
    running = 0
    completed = 0
    done = asyncio.Event()

    async def handler(job):  # type: ignore[no-untyped-def]
        nonlocal max_running, running, completed
        running += 1
        max_running = max(max_running, running)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        running -= 1
        completed += 1
        if completed == len(jobs):
            done.set()
        return {"job_id": job.id}

    dispatcher = Dispatcher(
        scheduler,
        handlers={"sync": handler},
        persistence_module=stub_queue_persistence,
        global_concurrency=2,
        pool_concurrency={"sync": 1},
        rng=random.Random(42),
    )

    task = asyncio.create_task(dispatcher.run())
    await asyncio.wait_for(done.wait(), timeout=1.0)
    dispatcher.request_stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert max_running == 1
    assert stub_queue_persistence.completed == [1, 2]


def test_dispatcher_resolves_pool_limit_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    stub_queue_persistence,
) -> None:
    monkeypatch.setenv("ORCH_POOL_SYNC", "7")

    async def noop(job):  # type: ignore[no-untyped-def]
        return None

    dispatcher = Dispatcher(
        _StubScheduler([]),
        handlers={"sync": noop},
        persistence_module=stub_queue_persistence,
        global_concurrency=5,
    )

    semaphore = dispatcher._get_pool_semaphore("sync")

    assert dispatcher._pool_limits["sync"] == 7
    assert semaphore._value == 7  # type: ignore[attr-defined]
