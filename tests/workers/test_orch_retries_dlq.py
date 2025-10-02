"""Retry and dead-letter behaviour for the orchestrator dispatcher."""

from __future__ import annotations

import asyncio
import random

import pytest

from app.config import ExternalCallPolicy
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
async def test_dispatcher_sends_job_to_dlq_after_max_retries(
    queue_job_factory,
    stub_queue_persistence,
) -> None:
    policy = ExternalCallPolicy(
        timeout_ms=10_000,
        retry_max=2,
        backoff_base_ms=250,
        jitter_pct=0.2,
    )
    job = queue_job_factory(job_id=11, job_type="sync", attempts=2, lease_timeout_seconds=30)
    scheduler = _StubScheduler([job])

    async def failing_handler(job):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    dispatcher = Dispatcher(
        scheduler,
        handlers={"sync": failing_handler},
        persistence_module=stub_queue_persistence,
        rng=random.Random(1234),
        external_policy=policy,
    )

    task = asyncio.create_task(dispatcher.run())

    async def _wait_for_dead_letter() -> None:
        while not stub_queue_persistence.dead_lettered:
            await asyncio.sleep(0)

    await asyncio.wait_for(_wait_for_dead_letter(), timeout=1.0)
    dispatcher.request_stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert stub_queue_persistence.dead_lettered
    record = stub_queue_persistence.dead_lettered[0]
    assert record["job_id"] == 11
    assert record["job_type"] == "sync"
    assert record["reason"] == "max_retries_exhausted"
    assert record["payload"]["attempts"] == 2
