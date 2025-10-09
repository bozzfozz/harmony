from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Mapping

import pytest

from app.config import settings
from app.models import QueueJobStatus
from app.orchestrator.scheduler import PriorityConfig, Scheduler
from app.workers.persistence import QueueJobDTO

if TYPE_CHECKING:
    from tests.conftest import StubQueuePersistence


class StubPersistence:
    def __init__(self, ready: Mapping[str, list[QueueJobDTO]]) -> None:
        self._ready: dict[str, list[QueueJobDTO]] = {
            job_type: list(jobs) for job_type, jobs in ready.items()
        }
        self._jobs: dict[int, QueueJobDTO] = {
            job.id: job for jobs in ready.values() for job in jobs
        }
        self.fetch_calls: list[str] = []
        self.lease_calls: list[tuple[int, str, int | None]] = []

    def fetch_ready(
        self, job_type: str, *, limit: int = 100
    ) -> list[QueueJobDTO]:  # noqa: D401 - signature parity
        self.fetch_calls.append(job_type)
        return list(self._ready.pop(job_type, []))

    def lease(
        self,
        job_id: int,
        *,
        job_type: str,
        lease_seconds: int | None = None,
    ) -> QueueJobDTO | None:  # noqa: D401 - signature parity
        self.lease_calls.append((job_id, job_type, lease_seconds))
        return self._jobs.get(job_id)


def make_job(job_id: int, job_type: str, priority: int, available_delta: int) -> QueueJobDTO:
    available_at = datetime.utcnow() + timedelta(seconds=available_delta)
    return QueueJobDTO(
        id=job_id,
        type=job_type,
        payload={},
        priority=priority,
        attempts=0,
        available_at=available_at,
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key=None,
        last_error=None,
        result_payload=None,
        lease_timeout_seconds=60,
    )


def test_priority_config_prefers_json_over_csv() -> None:
    env = {
        "ORCH_PRIORITY_JSON": '{"sync": 200, "matching": 100}',
        "ORCH_PRIORITY_CSV": "sync:1,matching:1",
    }
    config = PriorityConfig.from_env(env)
    assert config.priorities == {"sync": 200, "matching": 100}
    assert config.job_types == ("sync", "matching")


def test_priority_config_falls_back_to_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    env: dict[str, str] = {
        "ORCH_PRIORITY_JSON": "{invalid}",
        "ORCH_PRIORITY_CSV": "sync:50,matching:25",
    }
    config = PriorityConfig.from_env(env)
    assert config.priorities == {"sync": 50, "matching": 25}


@pytest.mark.asyncio
async def test_scheduler_leases_jobs_in_priority_order(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="app.orchestrator.scheduler")
    caplog.set_level("INFO", logger="app.orchestrator.metrics")

    jobs = {
        "sync": [make_job(1, "sync", 200, 5), make_job(2, "sync", 150, 3)],
        "matching": [make_job(3, "matching", 250, 1)],
    }
    stub = StubPersistence(jobs)
    config = PriorityConfig(priorities={"sync": 1, "matching": 1})
    scheduler = Scheduler(
        priority_config=config,
        poll_interval_ms=10,
        visibility_timeout=42,
        persistence_module=stub,
    )

    lifespan = asyncio.Event()
    run_task = asyncio.create_task(scheduler.run(lifespan))

    while len(stub.lease_calls) < 3:
        await asyncio.sleep(0)

    scheduler.request_stop()
    await run_task

    assert stub.fetch_calls == ["matching", "sync"]
    assert [call[:2] for call in stub.lease_calls] == [
        (3, "matching"),
        (1, "sync"),
        (2, "sync"),
    ]
    assert all(call[2] == 42 for call in stub.lease_calls)

    lease_records = [
        record
        for record in caplog.records
        if getattr(record, "event", "") == "orchestrator.lease"
    ]
    lease_events = [
        (record.job_type, record.entity_id, record.status)
        for record in lease_records
    ]
    assert lease_events == [
        ("matching", "3", "leased"),
        ("sync", "1", "leased"),
        ("sync", "2", "leased"),
    ]
    assert all(
        isinstance(record.duration_ms, int) and record.duration_ms >= 0
        for record in lease_records
    )
    assert {record.name for record in lease_records} == {"app.orchestrator.metrics"}


@pytest.mark.asyncio
async def test_scheduler_stops_when_lifespan_signal_set() -> None:
    config = PriorityConfig(priorities={"sync": 1})
    stub = StubPersistence({"sync": []})
    scheduler = Scheduler(priority_config=config, poll_interval_ms=10, persistence_module=stub)

    lifespan = asyncio.Event()
    task = asyncio.create_task(scheduler.run(lifespan))
    lifespan.set()
    await asyncio.wait_for(task, timeout=1)


def test_scheduler_backpressure_increases_interval() -> None:
    config = PriorityConfig(priorities={"sync": 1})
    stub = StubPersistence({"sync": []})
    scheduler = Scheduler(
        priority_config=config,
        poll_interval_ms=10,
        poll_interval_max_ms=40,
        idle_backoff_multiplier=2.0,
        persistence_module=stub,
    )

    assert scheduler.poll_interval == pytest.approx(0.01)

    scheduler.lease_ready_jobs()
    assert scheduler.poll_interval == pytest.approx(0.02)

    scheduler.lease_ready_jobs()
    assert scheduler.poll_interval == pytest.approx(0.04)

    scheduler.lease_ready_jobs()
    assert scheduler.poll_interval == pytest.approx(0.04)


def test_scheduler_backpressure_resets_after_work() -> None:
    config = PriorityConfig(priorities={"sync": 1})
    stub = StubPersistence({"sync": [make_job(1, "sync", 100, 0)]})
    scheduler = Scheduler(
        priority_config=config,
        poll_interval_ms=10,
        poll_interval_max_ms=40,
        idle_backoff_multiplier=2.0,
        persistence_module=stub,
    )

    scheduler.lease_ready_jobs()
    assert scheduler.poll_interval == pytest.approx(0.01)

    scheduler.lease_ready_jobs()
    assert scheduler.poll_interval > 0.01


def test_priority_state_isolated_between_runs(
    stub_queue_persistence: StubQueuePersistence,
) -> None:
    base_config = replace(
        settings.orchestrator,
        priority_map={"sync": 10},
    )
    scheduler_one = Scheduler(
        config=base_config,
        poll_interval_ms=5,
        persistence_module=stub_queue_persistence,
    )

    base_config.priority_map["sync"] = 99
    scheduler_two = Scheduler(
        config=base_config,
        poll_interval_ms=5,
        persistence_module=stub_queue_persistence,
    )

    assert scheduler_one._priority.get("sync") == 10
    assert scheduler_two._priority.get("sync") == 99
    assert settings.orchestrator.priority_map.get("sync") != 99
