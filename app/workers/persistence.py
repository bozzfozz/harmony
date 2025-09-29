"""Persistence helpers for worker job queues with leases and idempotency."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Sequence

from sqlalchemy import and_, or_, select

from app.db import session_scope
from app.logging import get_logger
from app.models import WorkerJob


logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _extract_priority(payload: dict) -> int:
    value = payload.get("priority", 0)
    try:
        return int(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        return 0


def _coerce_int(value: object, default: int) -> int:
    try:
        candidate = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return candidate if candidate >= 0 else default


def _load_visibility_timeout(payload: dict | None = None) -> int:
    payload_value = (payload or {}).get("visibility_timeout")
    env_value = os.getenv("WORKER_VISIBILITY_TIMEOUT_S")
    default_seconds = 60
    resolved = _coerce_int(payload_value, _coerce_int(env_value, default_seconds))
    return max(5, resolved)


def _derive_job_key(worker: str, payload: dict) -> str | None:
    key_candidate = payload.get("idempotency_key") or payload.get("job_id")
    if key_candidate is None:
        return None

    if isinstance(key_candidate, (dict, list, tuple, set)):
        serialised = json.dumps(key_candidate, sort_keys=True, default=str)
    else:
        serialised = str(key_candidate)
    digest = hashlib.sha256(f"{worker}:{serialised}".encode("utf-8")).hexdigest()
    return digest


@dataclass(slots=True)
class QueuedJob:
    """In-memory representation of a worker job stored in the database."""

    id: int
    payload: dict
    priority: int = 0
    attempts: int = 0
    lease_expires_at: datetime | None = None
    visibility_timeout: int = 60
    job_key: str | None = None


class PersistentJobQueue:
    """Provide CRUD helpers for worker job persistence with leasing semantics."""

    def __init__(self, worker_name: str) -> None:
        self._worker = worker_name

    # ------------------------------------------------------------------
    # enqueue helpers
    # ------------------------------------------------------------------
    def enqueue(
        self,
        payload: dict,
        *,
        scheduled_at: datetime | None = None,
        visibility_timeout: int | None = None,
    ) -> QueuedJob:
        """Persist a single job and return its representation."""

        job_key = _derive_job_key(self._worker, payload)
        effective_visibility = _load_visibility_timeout(payload)
        if visibility_timeout is not None:
            effective_visibility = max(5, int(visibility_timeout))

        now = _utcnow()
        scheduled_time = scheduled_at or now

        with session_scope() as session:
            existing: WorkerJob | None = None
            if job_key is not None:
                stmt = (
                    select(WorkerJob)
                    .where(
                        WorkerJob.worker == self._worker,
                        WorkerJob.job_key == job_key,
                    )
                    .limit(1)
                )
                existing = session.execute(stmt).scalars().first()

            if existing is not None:
                existing.payload = dict(payload)
                existing.state = "queued"
                existing.scheduled_at = scheduled_time
                existing.updated_at = now
                existing.lease_expires_at = None
                existing.last_error = None
                existing.stop_reason = None
                existing.visibility_timeout = effective_visibility
                session.add(existing)
                session.flush()
                logger.info(
                    "event=worker_enqueue worker=%s job_id=%s deduped=true",
                    self._worker,
                    existing.id,
                )
                return self._to_job(existing)

            job = WorkerJob(
                worker=self._worker,
                payload=dict(payload),
                scheduled_at=scheduled_time,
                visibility_timeout=effective_visibility,
                job_key=job_key,
            )
            session.add(job)
            session.flush()
            logger.info(
                "event=worker_enqueue worker=%s job_id=%s deduped=false",
                self._worker,
                job.id,
            )
            return self._to_job(job)

    def enqueue_many(self, payloads: Iterable[dict]) -> List[QueuedJob]:
        """Persist a batch of payloads returning their job handles."""

        jobs: List[QueuedJob] = []
        for payload in payloads:
            jobs.append(self.enqueue(payload))
        return jobs

    # ------------------------------------------------------------------
    # query helpers
    # ------------------------------------------------------------------
    def list_pending(self) -> List[QueuedJob]:
        """Return queued jobs and requeue any expired leases."""

        now = _utcnow()
        with session_scope() as session:
            stmt = (
                select(WorkerJob)
                .where(
                    WorkerJob.worker == self._worker,
                    or_(
                        WorkerJob.state == "queued",
                        and_(
                            WorkerJob.state == "running",
                            WorkerJob.lease_expires_at.is_not(None),
                            WorkerJob.lease_expires_at <= now,
                        ),
                    ),
                )
                .order_by(WorkerJob.scheduled_at.asc())
            )
            jobs = session.execute(stmt).scalars().all()

            queued: List[QueuedJob] = []
            for db_job in jobs:
                if db_job.state == "running":
                    db_job.state = "queued"
                    db_job.lease_expires_at = None
                    db_job.updated_at = now
                    session.add(db_job)
                queued.append(self._to_job(db_job))

            return queued

    # ------------------------------------------------------------------
    # lifecycle transitions
    # ------------------------------------------------------------------
    def mark_running(self, job_id: int, *, visibility_timeout: int | None = None) -> None:
        with session_scope() as session:
            job = session.get(WorkerJob, job_id)
            if job is None:
                return
            now = _utcnow()
            effective_visibility = (
                max(5, int(visibility_timeout))
                if visibility_timeout is not None
                else _load_visibility_timeout(job.payload or {})
            )
            job.state = "running"
            job.attempts += 1
            job.updated_at = now
            job.visibility_timeout = effective_visibility
            job.lease_expires_at = now + timedelta(seconds=effective_visibility)
            session.add(job)

    def extend_lease(self, job_id: int, *, visibility_timeout: int | None = None) -> bool:
        with session_scope() as session:
            job = session.get(WorkerJob, job_id)
            if job is None or job.state != "running":
                return False
            now = _utcnow()
            effective_visibility = (
                max(5, int(visibility_timeout))
                if visibility_timeout is not None
                else (job.visibility_timeout or _load_visibility_timeout(job.payload or {}))
            )
            job.visibility_timeout = effective_visibility
            job.lease_expires_at = now + timedelta(seconds=effective_visibility)
            job.updated_at = now
            session.add(job)
            logger.debug(
                "event=worker_heartbeat worker=%s job_id=%s lease_expires_at=%s",
                self._worker,
                job_id,
                job.lease_expires_at,
            )
            return True

    def mark_completed(self, job_id: int) -> None:
        with session_scope() as session:
            job = session.get(WorkerJob, job_id)
            if job is None:
                return
            job.state = "completed"
            job.last_error = None
            job.lease_expires_at = None
            job.stop_reason = None
            job.updated_at = _utcnow()
            session.add(job)

    def mark_failed(
        self,
        job_id: int,
        error: str,
        *,
        stop_reason: str | None = None,
        redeliver: bool = False,
        delay_seconds: int | None = None,
    ) -> None:
        with session_scope() as session:
            job = session.get(WorkerJob, job_id)
            if job is None:
                return
            now = _utcnow()
            job.last_error = error
            job.stop_reason = stop_reason
            if redeliver:
                job.state = "queued"
                job.scheduled_at = now + timedelta(seconds=max(0, delay_seconds or 0))
                job.lease_expires_at = None
            else:
                job.state = "failed"
                job.lease_expires_at = None
            job.updated_at = now
            session.add(job)

    def requeue_incomplete(self) -> None:
        with session_scope() as session:
            now = _utcnow()
            stmt = select(WorkerJob).where(
                WorkerJob.worker == self._worker,
                WorkerJob.state == "running",
            )
            jobs = session.execute(stmt).scalars().all()
            for job in jobs:
                if job.lease_expires_at and job.lease_expires_at > now:
                    continue
                job.state = "queued"
                job.lease_expires_at = None
                job.updated_at = now
                session.add(job)

    def update_priority(self, job_id: str, priority: int) -> bool:
        try:
            identifier = int(job_id)
        except (TypeError, ValueError):
            logger.error(
                "event=worker_priority_update worker=%s job_id=%s status=invalid_id",
                self._worker,
                job_id,
            )
            return False

        with session_scope() as session:
            job = session.get(WorkerJob, identifier)
            if job is None or job.worker != self._worker:
                logger.error(
                    "event=worker_priority_update worker=%s job_id=%s status=missing",
                    self._worker,
                    job_id,
                )
                return False

            if job.state not in {"queued", "retrying"}:
                logger.error(
                    "event=worker_priority_update worker=%s job_id=%s status=invalid_state state=%s",
                    self._worker,
                    job_id,
                    job.state,
                )
                return False

            payload = dict(job.payload or {})
            payload["priority"] = int(priority)

            files = payload.get("files")
            if isinstance(files, Sequence):
                updated_files: List[dict] = []
                for file_info in files:
                    if isinstance(file_info, dict):
                        updated = dict(file_info)
                        updated["priority"] = int(priority)
                        updated_files.append(updated)
                    else:  # pragma: no cover - guard against corrupted payloads
                        updated_files.append(file_info)
                payload["files"] = updated_files

            job.payload = payload
            job_priority = _extract_priority(payload)
            now = _utcnow()
            job.updated_at = now
            job.scheduled_at = now
            job.state = "queued"
            session.add(job)

        logger.info(
            "event=worker_priority_update worker=%s job_id=%s priority=%s status=success",
            self._worker,
            job_id,
            job_priority,
        )
        return True

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def _to_job(self, record: WorkerJob) -> QueuedJob:
        return QueuedJob(
            id=int(record.id),
            payload=dict(record.payload or {}),
            priority=_extract_priority(record.payload or {}),
            attempts=int(record.attempts or 0),
            lease_expires_at=record.lease_expires_at,
            visibility_timeout=int(record.visibility_timeout or _load_visibility_timeout()),
            job_key=record.job_key,
        )
