"""Persistence helpers for worker job queues."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List

from sqlalchemy import select

from app.db import session_scope
from app.models import WorkerJob


@dataclass(slots=True)
class QueuedJob:
    """In-memory representation of a worker job stored in the database."""

    id: int
    payload: dict


class PersistentJobQueue:
    """Provide simple CRUD helpers for worker job persistence."""

    def __init__(self, worker_name: str) -> None:
        self._worker = worker_name

    def enqueue(self, payload: dict) -> QueuedJob:
        with session_scope() as session:
            job = WorkerJob(worker=self._worker, payload=payload)
            session.add(job)
            session.flush()
            return QueuedJob(id=job.id, payload=dict(payload))

    def enqueue_many(self, payloads: Iterable[dict]) -> List[QueuedJob]:
        jobs: List[QueuedJob] = []
        with session_scope() as session:
            now = datetime.utcnow()
            for payload in payloads:
                job = WorkerJob(
                    worker=self._worker,
                    payload=payload,
                    scheduled_at=now,
                )
                session.add(job)
                session.flush()
                jobs.append(QueuedJob(id=job.id, payload=dict(payload)))
        return jobs

    def list_pending(self) -> List[QueuedJob]:
        with session_scope() as session:
            jobs = (
                session.execute(
                    select(WorkerJob)
                    .where(
                        WorkerJob.worker == self._worker,
                        WorkerJob.state.in_(["queued", "running"]),
                    )
                    .order_by(WorkerJob.created_at.asc())
                )
                .scalars()
                .all()
            )
            results: List[QueuedJob] = []
            for job in jobs:
                job.state = "queued"
                job.updated_at = datetime.utcnow()
                results.append(QueuedJob(id=job.id, payload=dict(job.payload)))
            return results

    def mark_running(self, job_id: int) -> None:
        with session_scope() as session:
            job = session.get(WorkerJob, job_id)
            if job is None:
                return
            job.state = "running"
            job.attempts += 1
            job.updated_at = datetime.utcnow()

    def mark_completed(self, job_id: int) -> None:
        with session_scope() as session:
            job = session.get(WorkerJob, job_id)
            if job is None:
                return
            job.state = "completed"
            job.last_error = None
            job.updated_at = datetime.utcnow()

    def mark_failed(self, job_id: int, error: str) -> None:
        with session_scope() as session:
            job = session.get(WorkerJob, job_id)
            if job is None:
                return
            job.state = "failed"
            job.last_error = error
            job.updated_at = datetime.utcnow()

    def requeue_incomplete(self) -> None:
        with session_scope() as session:
            jobs = (
                session.execute(
                    select(WorkerJob).where(
                        WorkerJob.worker == self._worker,
                        WorkerJob.state == "running",
                    )
                )
                .scalars()
                .all()
            )
            now = datetime.utcnow()
            for job in jobs:
                job.state = "queued"
                job.updated_at = now
