"""Persistence helpers for worker job queues."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List

from sqlalchemy import select

from app.db import session_scope
from app.models import WorkerJob
from app.logging import get_logger


def _extract_priority(payload: dict) -> int:
    value = payload.get("priority", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


logger = get_logger(__name__)


@dataclass(slots=True)
class QueuedJob:
    """In-memory representation of a worker job stored in the database."""

    id: int
    payload: dict
    priority: int = 0


class PersistentJobQueue:
    """Provide simple CRUD helpers for worker job persistence."""

    def __init__(self, worker_name: str) -> None:
        self._worker = worker_name

    def enqueue(self, payload: dict) -> QueuedJob:
        with session_scope() as session:
            job = WorkerJob(worker=self._worker, payload=payload)
            session.add(job)
            session.flush()
            return QueuedJob(
                id=job.id,
                payload=dict(payload),
                priority=_extract_priority(payload),
            )

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
                jobs.append(
                    QueuedJob(
                        id=job.id,
                        payload=dict(payload),
                        priority=_extract_priority(payload),
                    )
                )
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
                results.append(
                    QueuedJob(
                        id=job.id,
                        payload=dict(job.payload),
                        priority=_extract_priority(job.payload),
                    )
                )
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

    def update_priority(self, job_id: str, priority: int) -> bool:
        try:
            identifier = int(job_id)
        except (TypeError, ValueError):
            logger.error(
                "Invalid job id %s supplied for priority update on worker %s",
                job_id,
                self._worker,
            )
            return False

        with session_scope() as session:
            job = session.get(WorkerJob, identifier)
            if job is None or job.worker != self._worker:
                logger.error(
                    "Worker job %s not found for worker %s during priority update",
                    job_id,
                    self._worker,
                )
                return False

            if job.state not in {"queued", "retrying"}:
                logger.error(
                    "Cannot update priority for job %s in state %s", job_id, job.state
                )
                return False

            payload = dict(job.payload or {})
            payload["priority"] = int(priority)

            files = payload.get("files")
            if isinstance(files, list):
                updated_files: List[dict] = []
                for file_info in files:
                    if isinstance(file_info, dict):
                        updated = dict(file_info)
                        updated["priority"] = int(priority)
                        updated_files.append(updated)
                    else:
                        updated_files.append(file_info)
                payload["files"] = updated_files

            job.payload = payload
            job_priority = _extract_priority(payload)
            now = datetime.utcnow()
            job.updated_at = now
            job.scheduled_at = now
            job.state = "queued"

        logger.info(
            "Updated priority for job %s on worker %s to %s",
            job_id,
            self._worker,
            job_priority,
        )
        return True
