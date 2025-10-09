"""Scheduler and heartbeat behaviour for orchestrator workers."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db import reset_engine_for_tests, session_scope
from app.models import QueueJob, QueueJobStatus
from app.orchestrator.scheduler import PriorityConfig, Scheduler
from app.workers import persistence

pytestmark = pytest.mark.postgres


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
async def test_heartbeat_failure_releases_job_for_redelivery() -> None:
    scheduler = Scheduler(
        priority_config=PriorityConfig(priorities={"sync": 100}),
        poll_interval_ms=0,
        visibility_timeout=10,
    )

    job = persistence.enqueue("sync", {"priority": 5, "visibility_timeout": 10})

    first_lease = scheduler.lease_ready_jobs()
    assert first_lease and first_lease[0].id == job.id

    assert persistence.heartbeat(job.id, job_type="sync") is True

    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        assert db_job.lease_expires_at is not None
        assert db_job.status == QueueJobStatus.LEASED.value

    expired_at = datetime.utcnow() - timedelta(seconds=1)
    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        db_job.lease_expires_at = expired_at
        db_job.available_at = expired_at
        db_job.status = QueueJobStatus.LEASED.value
        session.add(db_job)

    assert persistence.heartbeat(job.id, job_type="sync") is False

    second_lease = scheduler.lease_ready_jobs()

    assert any(item.id == job.id for item in second_lease)
    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        assert db_job.status == QueueJobStatus.LEASED.value


def test_lease_and_redelivery_after_visibility_timeout() -> None:
    reset_engine_for_tests()
    scheduler = Scheduler(
        priority_config=PriorityConfig(priorities={"sync": 100}),
        poll_interval_ms=0,
        visibility_timeout=15,
    )

    job = persistence.enqueue("sync", {"priority": 5, "visibility_timeout": 15})

    first_lease = scheduler.lease_ready_jobs()
    assert [item.id for item in first_lease] == [job.id]
    first_deadline = first_lease[0].lease_expires_at

    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        assert db_job.status == QueueJobStatus.LEASED.value
        assert db_job.attempts == 1

    expired_at = datetime.utcnow() - timedelta(seconds=1)
    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        db_job.lease_expires_at = expired_at
        db_job.available_at = expired_at
        db_job.status = QueueJobStatus.LEASED.value
        session.add(db_job)

    second_lease = scheduler.lease_ready_jobs()
    assert [item.id for item in second_lease] == [job.id]

    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        assert db_job.status == QueueJobStatus.LEASED.value
        assert db_job.attempts == 2
        assert db_job.lease_expires_at is not None
        assert first_deadline is not None and db_job.lease_expires_at > first_deadline


def test_heartbeat_extends_lease_in_long_running_handler() -> None:
    reset_engine_for_tests()
    scheduler = Scheduler(
        priority_config=PriorityConfig(priorities={"sync": 100}),
        poll_interval_ms=0,
        visibility_timeout=20,
    )

    job = persistence.enqueue("sync", {"priority": 1, "visibility_timeout": 20})
    leased = scheduler.lease_ready_jobs()
    assert leased and leased[0].id == job.id
    first_deadline = leased[0].lease_expires_at

    assert persistence.heartbeat(job.id, job_type="sync", lease_seconds=20) is True

    with session_scope() as session:
        db_job = session.get(QueueJob, job.id)
        assert db_job is not None
        assert db_job.status == QueueJobStatus.LEASED.value
        assert db_job.lease_expires_at is not None
        assert first_deadline is not None and db_job.lease_expires_at >= first_deadline
