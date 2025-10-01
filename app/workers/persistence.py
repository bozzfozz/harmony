"""Persistence helpers for the generic `QueueJob` worker queue."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, List, Mapping, Sequence

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.logging import get_logger
from app.models import QueueJob, QueueJobStatus


logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _resolve_priority(payload: Mapping[str, Any]) -> int:
    priority_value = payload.get("priority", 0)
    return _safe_int(priority_value, 0)


def _resolve_visibility_timeout(payload: Mapping[str, Any], override: int | None = None) -> int:
    if override is not None:
        return max(5, int(override))

    payload_value = payload.get("visibility_timeout")
    env_value = os.getenv("WORKER_VISIBILITY_TIMEOUT_S")
    resolved = _safe_int(payload_value, _safe_int(env_value, 60))
    return max(5, resolved)


def _derive_idempotency_key(job_type: str, payload: Mapping[str, Any]) -> str | None:
    candidate = payload.get("idempotency_key") or payload.get("job_id")
    if candidate is None:
        return None

    if isinstance(candidate, (dict, list, tuple, set)):
        serialised = json.dumps(candidate, sort_keys=True, default=str)
    else:
        serialised = str(candidate)
    digest = hashlib.sha256(f"{job_type}:{serialised}".encode("utf-8")).hexdigest()
    return digest


@dataclass(slots=True)
class QueueJobDTO:
    """Lightweight data transfer object for queue jobs."""

    id: int
    type: str
    payload: dict[str, Any]
    priority: int
    attempts: int
    available_at: datetime
    lease_expires_at: datetime | None
    status: QueueJobStatus
    idempotency_key: str | None
    last_error: str | None = None
    result_payload: dict[str, Any] | None = None
    lease_timeout_seconds: int = 60


def _to_dto(record: QueueJob) -> QueueJobDTO:
    payload = dict(record.payload or {})
    return QueueJobDTO(
        id=int(record.id),
        type=str(record.type),
        payload=payload,
        priority=int(record.priority or 0),
        attempts=int(record.attempts or 0),
        available_at=record.available_at,
        lease_expires_at=record.lease_expires_at,
        status=QueueJobStatus(record.status),
        idempotency_key=record.idempotency_key,
        last_error=record.last_error,
        result_payload=dict(record.result_payload or {}) if record.result_payload else None,
        lease_timeout_seconds=_resolve_visibility_timeout(payload),
    )


def _refresh_instance(session: Session, record: QueueJob) -> QueueJobDTO:
    session.flush()
    session.refresh(record)
    return _to_dto(record)


def enqueue(
    job_type: str,
    payload: Mapping[str, Any],
    *,
    priority: int | None = None,
    available_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> QueueJobDTO:
    """Insert a new queue job or upsert by idempotency key."""

    now = _utcnow()
    scheduled_for = available_at or now
    payload_dict = dict(payload)
    dedupe_key = idempotency_key or _derive_idempotency_key(job_type, payload_dict)
    resolved_priority = priority if priority is not None else _resolve_priority(payload_dict)

    with session_scope() as session:
        existing: QueueJob | None = None
        if dedupe_key:
            stmt: Select[QueueJob] = (
                select(QueueJob)
                .where(
                    QueueJob.type == job_type,
                    QueueJob.idempotency_key == dedupe_key,
                )
                .order_by(QueueJob.id.desc())
                .limit(1)
            )
            existing = session.execute(stmt).scalars().first()

        if existing and existing.status not in {
            QueueJobStatus.COMPLETED.value,
            QueueJobStatus.CANCELLED.value,
        }:
            logger.info(
                "event=queue.enqueue job_type=%s job_id=%s deduped=true",
                job_type,
                existing.id,
            )
            existing.payload = payload_dict
            existing.priority = resolved_priority
            existing.available_at = scheduled_for
            existing.status = QueueJobStatus.PENDING.value
            existing.lease_expires_at = None
            existing.last_error = None
            existing.result_payload = None
            existing.updated_at = now
            session.add(existing)
            return _refresh_instance(session, existing)

        record = QueueJob(
            type=job_type,
            payload=payload_dict,
            priority=resolved_priority,
            available_at=scheduled_for,
            idempotency_key=dedupe_key,
            status=QueueJobStatus.PENDING.value,
        )
        session.add(record)
        logger.info(
            "event=queue.enqueue job_type=%s deduped=false",
            job_type,
        )
        return _refresh_instance(session, record)


def enqueue_many(
    job_type: str,
    payloads: Iterable[Mapping[str, Any]],
    *,
    priority: int | None = None,
) -> List[QueueJobDTO]:
    """Persist a batch of jobs returning their DTO representations."""

    jobs: List[QueueJobDTO] = []
    for payload in payloads:
        jobs.append(enqueue(job_type, payload, priority=priority))
    return jobs


def _release_expired_leases(session: Session, job_type: str, now: datetime) -> bool:
    stmt: Select[QueueJob] = (
        select(QueueJob)
        .where(
            QueueJob.type == job_type,
            QueueJob.status == QueueJobStatus.LEASED.value,
            QueueJob.lease_expires_at.is_not(None),
            QueueJob.lease_expires_at <= now,
        )
        .with_for_update(skip_locked=True)
    )
    expired = session.execute(stmt).scalars().all()
    if not expired:
        return False

    released_at = _utcnow()
    for record in expired:
        record.status = QueueJobStatus.PENDING.value
        record.lease_expires_at = None
        record.available_at = released_at
        record.updated_at = released_at
        session.add(record)

    session.flush()
    return True


def fetch_ready(job_type: str, *, limit: int = 100) -> List[QueueJobDTO]:
    """Return queue jobs ready for processing (expired leases are reset)."""

    now = _utcnow()
    with session_scope() as session:
        released = _release_expired_leases(session, job_type, now)
        if released:
            now = _utcnow()

        stmt: Select[QueueJob] = (
            select(QueueJob)
            .where(
                QueueJob.type == job_type,
                QueueJob.status == QueueJobStatus.PENDING.value,
                QueueJob.available_at <= now,
            )
            .order_by(
                QueueJob.priority.desc(),
                QueueJob.available_at.asc(),
                QueueJob.id.asc(),
            )
            .limit(limit)
        )
        records = session.execute(stmt).scalars().all()
        return [_to_dto(record) for record in records]


def lease(
    job_id: int,
    *,
    job_type: str,
    lease_seconds: int | None = None,
) -> QueueJobDTO | None:
    """Attempt to lease a job for execution."""

    now = _utcnow()
    with session_scope() as session:
        stmt: Select[QueueJob] = (
            select(QueueJob)
            .where(QueueJob.id == job_id, QueueJob.type == job_type)
            .with_for_update(skip_locked=True)
        )
        record = session.execute(stmt).scalars().first()
        if record is None:
            return None

        if record.status not in {
            QueueJobStatus.PENDING.value,
            QueueJobStatus.LEASED.value,
        }:
            return None

        if record.status == QueueJobStatus.PENDING.value and record.available_at > now:
            return None

        if record.status == QueueJobStatus.LEASED.value and record.lease_expires_at:
            if record.lease_expires_at > now:
                return None

        timeout = _resolve_visibility_timeout(record.payload or {}, lease_seconds)
        record.status = QueueJobStatus.LEASED.value
        record.attempts = int(record.attempts or 0) + 1
        record.lease_expires_at = now + timedelta(seconds=timeout)
        record.updated_at = now
        session.add(record)
        return _refresh_instance(session, record)


def heartbeat(
    job_id: int,
    *,
    job_type: str,
    lease_seconds: int | None = None,
) -> bool:
    """Extend the lease for an in-progress job."""

    now = _utcnow()
    with session_scope() as session:
        stmt: Select[QueueJob] = (
            select(QueueJob)
            .where(
                QueueJob.id == job_id,
                QueueJob.type == job_type,
            )
            .with_for_update(skip_locked=True)
        )
        record = session.execute(stmt).scalars().first()
        if record is None:
            return False

        if record.status != QueueJobStatus.LEASED.value:
            return False

        if record.lease_expires_at and record.lease_expires_at <= now:
            return False

        timeout = _resolve_visibility_timeout(record.payload or {}, lease_seconds)
        record.lease_expires_at = now + timedelta(seconds=timeout)
        record.updated_at = now
        session.add(record)
        return True


def complete(
    job_id: int,
    *,
    job_type: str,
    result_payload: Mapping[str, Any] | None = None,
) -> bool:
    """Mark a leased job as completed."""

    now = _utcnow()
    with session_scope() as session:
        record = session.get(QueueJob, job_id)
        if record is None or record.type != job_type:
            return False

        record.status = QueueJobStatus.COMPLETED.value
        record.lease_expires_at = None
        record.last_error = None
        record.result_payload = dict(result_payload or {}) or None
        record.updated_at = now
        session.add(record)
        return True


def fail(
    job_id: int,
    *,
    job_type: str,
    error: str | None = None,
    retry_in: int | None = None,
    available_at: datetime | None = None,
) -> bool:
    """Mark a job as failed or requeue it for another attempt."""

    now = _utcnow()
    with session_scope() as session:
        record = session.get(QueueJob, job_id)
        if record is None or record.type != job_type:
            return False

        record.last_error = error
        record.updated_at = now
        record.lease_expires_at = None

        if retry_in is not None or available_at is not None:
            delay = max(0, int(retry_in or 0))
            next_available = available_at or (now + timedelta(seconds=delay))
            record.available_at = next_available
            record.status = QueueJobStatus.PENDING.value
        else:
            record.status = QueueJobStatus.FAILED.value
        session.add(record)
        return True


def to_dlq(
    job_id: int,
    *,
    job_type: str,
    reason: str,
    payload: Mapping[str, Any] | None = None,
) -> bool:
    """Move a job to the dead-letter queue state."""

    now = _utcnow()
    with session_scope() as session:
        record = session.get(QueueJob, job_id)
        if record is None or record.type != job_type:
            return False

        record.status = QueueJobStatus.CANCELLED.value
        record.lease_expires_at = None
        record.last_error = reason
        record.result_payload = dict(payload or {}) or None
        record.updated_at = now
        session.add(record)
        return True


def release_active_leases(job_type: str) -> None:
    """Release all leases for a job type regardless of expiry."""

    now = _utcnow()
    with session_scope() as session:
        stmt = (
            update(QueueJob)
            .where(
                QueueJob.type == job_type,
                QueueJob.status == QueueJobStatus.LEASED.value,
            )
            .values(
                status=QueueJobStatus.PENDING.value,
                lease_expires_at=None,
                updated_at=now,
            )
        )
        session.execute(stmt)


def find_by_idempotency(job_type: str, idempotency_key: str) -> QueueJobDTO | None:
    """Return a job matching the given idempotency key if available."""

    with session_scope() as session:
        stmt: Select[QueueJob] = (
            select(QueueJob)
            .where(
                QueueJob.type == job_type,
                QueueJob.idempotency_key == idempotency_key,
            )
            .order_by(QueueJob.id.desc())
            .limit(1)
        )
        record = session.execute(stmt).scalars().first()
        return _to_dto(record) if record else None


def update_priority(
    job_id: int | str,
    priority: int,
    *,
    job_type: str,
) -> bool:
    """Update the priority of a pending job."""

    try:
        identifier = int(job_id)
    except (TypeError, ValueError):
        logger.error(
            "event=queue.priority_update job_type=%s job_id=%s status=invalid_id",
            job_type,
            job_id,
        )
        return False

    with session_scope() as session:
        record = session.get(QueueJob, identifier)
        if record is None or record.type != job_type:
            logger.error(
                "event=queue.priority_update job_type=%s job_id=%s status=missing",
                job_type,
                job_id,
            )
            return False

        if record.status not in {
            QueueJobStatus.PENDING.value,
            QueueJobStatus.FAILED.value,
        }:
            logger.error(
                "event=queue.priority_update job_type=%s job_id=%s status=invalid_state state=%s",
                job_type,
                job_id,
                record.status,
            )
            return False

        payload = dict(record.payload or {})
        payload["priority"] = int(priority)

        files = payload.get("files")
        if isinstance(files, Sequence):
            updated_files: list[dict[str, Any]] = []
            for file_info in files:
                if isinstance(file_info, Mapping):
                    item = dict(file_info)
                    item["priority"] = int(priority)
                    updated_files.append(item)
                else:  # pragma: no cover - corrupted payload guard
                    updated_files.append(file_info)  # type: ignore[arg-type]
            payload["files"] = updated_files

        now = _utcnow()
        record.payload = payload
        record.priority = int(priority)
        record.status = QueueJobStatus.PENDING.value
        record.available_at = now
        record.updated_at = now
        session.add(record)

    logger.info(
        "event=queue.priority_update job_type=%s job_id=%s priority=%s status=success",
        job_type,
        job_id,
        priority,
    )
    return True


def count_active_leases(job_type: str) -> int:
    """Return the number of currently leased jobs for the given type."""

    with session_scope() as session:
        result = session.execute(
            select(func.count())
            .select_from(QueueJob)
            .where(
                QueueJob.type == job_type,
                QueueJob.status == QueueJobStatus.LEASED.value,
            )
        )
        count = result.scalar_one_or_none()
    return int(count or 0)


__all__ = [
    "QueueJobDTO",
    "enqueue",
    "enqueue_many",
    "fetch_ready",
    "lease",
    "heartbeat",
    "complete",
    "fail",
    "to_dlq",
    "release_active_leases",
    "find_by_idempotency",
    "update_priority",
    "count_active_leases",
]
