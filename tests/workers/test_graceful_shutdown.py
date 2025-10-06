"""Tests covering graceful shutdown behaviour of queue leases."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models import QueueJob, QueueJobStatus
from app.workers.persistence import enqueue, lease, release_active_leases


def test_release_active_leases_resets_all_jobs() -> None:
    active_job = enqueue("artist_refresh", {"idempotency_key": "active"})
    expired_job = enqueue("artist_refresh", {"idempotency_key": "expired"})

    assert lease(active_job.id, job_type="artist_refresh", lease_seconds=30) is not None
    assert lease(expired_job.id, job_type="artist_refresh", lease_seconds=5) is not None

    with session_scope() as session:
        db_job = session.get(QueueJob, expired_job.id)
        assert db_job is not None
        db_job.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.add(db_job)

    release_active_leases("artist_refresh")

    with session_scope() as session:
        active = session.get(QueueJob, active_job.id)
        expired = session.get(QueueJob, expired_job.id)
        assert active is not None and active.status == QueueJobStatus.PENDING.value
        assert expired is not None and expired.status == QueueJobStatus.PENDING.value
