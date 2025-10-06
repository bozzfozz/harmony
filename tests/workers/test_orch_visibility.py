"""Scheduler and heartbeat behaviour for orchestrator workers."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db import session_scope
from app.models import QueueJob, QueueJobStatus
from app.orchestrator.scheduler import PriorityConfig, Scheduler
from app.workers import persistence


def test_scheduler_orders_jobs_by_priority_and_time(
    queue_job_factory,
    stub_queue_persistence,
) -> None:
    base = datetime(2024, 1, 1, 12, 0, 0)
    job_retry = queue_job_factory(
        job_id=1,
        job_type="retry",
        priority=10,
        available_at=base + timedelta(seconds=5),
    )
    job_sync_early = queue_job_factory(
        job_id=2,
        job_type="sync",
        priority=20,
        available_at=base + timedelta(seconds=1),
    )
    job_sync_late = queue_job_factory(
        job_id=3,
        job_type="sync",
        priority=20,
        available_at=base + timedelta(seconds=3),
    )
    job_watchlist = queue_job_factory(
        job_id=4,
        job_type="artist_refresh",
        priority=50,
        available_at=base + timedelta(seconds=2),
    )

    for job in (job_retry, job_sync_early, job_sync_late, job_watchlist):
        stub_queue_persistence.add_ready(job)

    config = PriorityConfig(priorities={"retry": 90, "sync": 60, "artist_refresh": 30})
    scheduler = Scheduler(
        priority_config=config,
        poll_interval_ms=10,
        visibility_timeout=30,
        persistence_module=stub_queue_persistence,
    )

    leased = scheduler.lease_ready_jobs()

    assert [job.id for job in leased] == [4, 2, 3, 1]
    assert all(call[2] == 30 for call in stub_queue_persistence.leases)


@pytest.mark.asyncio
async def test_heartbeat_failure_releases_job_for_redelivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = datetime(2024, 1, 1, 8, 0, 0)

    def fake_now() -> datetime:
        return current

    monkeypatch.setattr("app.workers.persistence._utcnow", fake_now)
    scheduler = Scheduler(
        priority_config=PriorityConfig(priorities={"sync": 100}),
        poll_interval_ms=0,
        visibility_timeout=10,
    )

    job = persistence.enqueue("sync", {"priority": 5, "visibility_timeout": 10})

    first_lease = scheduler.lease_ready_jobs()
    assert first_lease and first_lease[0].id == job.id

    current = current + timedelta(seconds=5)
    assert persistence.heartbeat(job.id, job_type="sync") is True

    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        assert db_job.lease_expires_at is not None
        assert db_job.status == QueueJobStatus.LEASED.value

    current = current + timedelta(seconds=20)
    assert persistence.heartbeat(job.id, job_type="sync") is False

    second_lease = scheduler.lease_ready_jobs()

    assert any(item.id == job.id for item in second_lease)
    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        assert db_job.status == QueueJobStatus.LEASED.value
