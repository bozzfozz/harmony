"""Persistence helpers for the generic `QueueJob` worker queue."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, List, Mapping, Sequence

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.db import session_scope
from app.logging import get_logger
from app.logging_events import log_event
from app.models import QueueJob, QueueJobStatus
from app.utils.idempotency import make_idempotency_key
from app.utils.jsonx import safe_dumps
from app.utils.time import now_utc


logger = get_logger(__name__)


def _utcnow() -> datetime:
    return now_utc().replace(tzinfo=None)


def _emit_worker_job_event(
    job: "QueueJobDTO", status: str, *, deduped: bool | None = None, **extra: Any
) -> None:
    payload: dict[str, Any] = {
        "component": "queue.persistence",
        "entity_id": str(job.id),
        "job_type": job.type,
        "status": status,
        "attempts": int(job.attempts),
    }
    if deduped is not None:
        payload["deduped"] = deduped
    payload.update({key: value for key, value in extra.items() if value is not None})
    log_event(logger, "worker.job", **payload)


def _emit_worker_tick(job_type: str, *, status: str, count: int | None = None) -> None:
    payload: dict[str, Any] = {
        "component": "queue.persistence",
        "job_type": job_type,
        "status": status,
    }
    if count is not None:
        payload["count"] = count
    log_event(logger, "worker.tick", **payload)


def _emit_retry_exhausted(job: "QueueJobDTO", *, stop_reason: str) -> None:
    log_event(
        logger,
        "worker.retry_exhausted",
        component="queue.persistence",
        entity_id=str(job.id),
        job_type=job.type,
        status="retry_exhausted",
        stop_reason=stop_reason,
        attempts=int(job.attempts),
    )


def _resolve_priority(payload: Mapping[str, Any]) -> int:
    priority_value = payload.get("priority", 0)
    try:
        parsed = int(priority_value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _resolve_visibility_timeout(payload: Mapping[str, Any], override: int | None = None) -> int:
    if override is not None:
        try:
            resolved_override = int(override)
        except (TypeError, ValueError):
            resolved_override = 0
        return max(5, resolved_override)

    payload_value = payload.get("visibility_timeout")
    from app.dependencies import get_app_config  # lazy import to avoid circular dependency
    config = get_app_config()
    worker_env = config.environment.workers
    env_override = worker_env.visibility_timeout_s
    resolved_default = (
        env_override
        if env_override is not None
        else settings.orchestrator.visibility_timeout_s
    )
    try:
        payload_resolved = (
            int(payload_value) if payload_value is not None else resolved_default
        )
    except (TypeError, ValueError):
        payload_resolved = resolved_default
    return max(5, payload_resolved)


def _derive_idempotency_key(job_type: str, payload: Mapping[str, Any]) -> str | None:
    candidate = payload.get("idempotency_key") or payload.get("job_id")
    if candidate is None:
        return None

    if isinstance(candidate, (dict, list, tuple, set)):
        serialised = safe_dumps(candidate)
    else:
        serialised = str(candidate)
    return make_idempotency_key(job_type, serialised)


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
    stop_reason: str | None = None
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
        stop_reason=record.stop_reason,
        lease_timeout_seconds=_resolve_visibility_timeout(payload),
    )


def _refresh_instance(session: Session, record: QueueJob) -> QueueJobDTO:
    session.flush()
    session.refresh(record)
    return _to_dto(record)


def _upsert_queue_job(
    session: Session,
    *,
    job_type: str,
    dedupe_key: str,
    payload: Mapping[str, Any],
    priority: int,
    scheduled_for: datetime,
    now: datetime,
) -> tuple[QueueJob, bool]:
    """Insert or update a queue job guarded by the idempotency key."""

    bind = session.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "") if bind else ""

    insert_values = {
        "type": job_type,
        "payload": dict(payload),
        "priority": priority,
        "available_at": scheduled_for,
        "idempotency_key": dedupe_key,
        "status": QueueJobStatus.PENDING.value,
        "stop_reason": None,
        "lease_expires_at": None,
        "last_error": None,
        "result_payload": None,
        "attempts": 0,
        "created_at": now,
        "updated_at": now,
    }

    if dialect_name in {"postgresql", "sqlite"}:
        insert_fn = pg_insert if dialect_name == "postgresql" else sqlite_insert
        insert_stmt = (
            insert_fn(QueueJob)
            .values(**insert_values)
            .on_conflict_do_nothing(
                index_elements=[QueueJob.type, QueueJob.idempotency_key]
            )
        )
        try:
            result = session.execute(insert_stmt)
        except OperationalError as exc:
            if dialect_name == "sqlite":
                message = str(getattr(exc, "orig", exc))
                if "ON CONFLICT" in message.upper():
                    logger.debug(
                        "Falling back to manual queue upsert due to sqlite ON CONFLICT error",
                        extra={
                            "event": "queue.sqlite_conflict_fallback",
                            "job_type": job_type,
                        },
                    )
                    session.rollback()
                else:  # pragma: no cover - unexpected sqlite error
                    raise
            else:  # pragma: no cover - unexpected non-sqlite error
                raise
        else:
            if result.rowcount:
                stmt = select(QueueJob).where(
                    QueueJob.type == job_type,
                    QueueJob.idempotency_key == dedupe_key,
                )
                record = session.execute(stmt).scalars().one()
                return record, False

    stmt: Select[QueueJob] = select(QueueJob).where(
        QueueJob.type == job_type,
        QueueJob.idempotency_key == dedupe_key,
    )
    if dialect_name not in {"", "sqlite"}:
        stmt = stmt.with_for_update()

    existing = session.execute(stmt).scalars().first()
    if existing is not None:
        previous_status = existing.status
        existing.payload = dict(payload)
        existing.priority = priority
        existing.available_at = scheduled_for
        existing.status = QueueJobStatus.PENDING.value
        existing.lease_expires_at = None
        existing.last_error = None
        existing.result_payload = None
        existing.stop_reason = None
        existing.updated_at = now
        if previous_status in {
            QueueJobStatus.COMPLETED.value,
            QueueJobStatus.CANCELLED.value,
        }:
            existing.attempts = 0
            deduped = False
        else:
            deduped = True
        session.add(existing)
        return existing, deduped

    record = QueueJob(**insert_values)
    session.add(record)
    return record, False


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
        if dedupe_key:
            record, deduped = _upsert_queue_job(
                session,
                job_type=job_type,
                dedupe_key=dedupe_key,
                payload=payload_dict,
                priority=resolved_priority,
                scheduled_for=scheduled_for,
                now=now,
            )
        else:
            record = QueueJob(
                type=job_type,
                payload=payload_dict,
                priority=resolved_priority,
                available_at=scheduled_for,
                idempotency_key=None,
                status=QueueJobStatus.PENDING.value,
                stop_reason=None,
                lease_expires_at=None,
                last_error=None,
                result_payload=None,
                attempts=0,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            deduped = False

        dto = _refresh_instance(session, record)
        _emit_worker_job_event(dto, "enqueued", deduped=deduped)
        return dto


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
        jobs = [_to_dto(record) for record in records]
    _emit_worker_tick(job_type, status="ready", count=len(jobs))
    return jobs


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
        dto = _refresh_instance(session, record)
    _emit_worker_job_event(dto, "leased", lease_timeout_s=timeout)
    return dto


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
    dto: QueueJobDTO | None = None
    with session_scope() as session:
        record = session.get(QueueJob, job_id)
        if record is None or record.type != job_type:
            return False

        record.status = QueueJobStatus.COMPLETED.value
        record.lease_expires_at = None
        record.last_error = None
        record.result_payload = dict(result_payload or {}) or None
        record.stop_reason = None
        record.updated_at = now
        session.add(record)
        dto = _refresh_instance(session, record)
    assert dto is not None
    _emit_worker_job_event(dto, "completed", has_result=dto.result_payload is not None)
    return True


def fail(
    job_id: int,
    *,
    job_type: str,
    error: str | None = None,
    retry_in: int | None = None,
    available_at: datetime | None = None,
    stop_reason: str | None = None,
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
            record.stop_reason = None
        else:
            record.status = QueueJobStatus.FAILED.value
            record.stop_reason = stop_reason
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
    dto: QueueJobDTO | None = None
    with session_scope() as session:
        record = session.get(QueueJob, job_id)
        if record is None or record.type != job_type:
            return False

        record.status = QueueJobStatus.CANCELLED.value
        record.lease_expires_at = None
        record.last_error = reason
        record.result_payload = dict(payload or {}) or None
        record.stop_reason = reason
        record.updated_at = now
        session.add(record)
        dto = _refresh_instance(session, record)
    assert dto is not None
    _emit_worker_job_event(dto, "dead_letter", stop_reason=reason)
    if reason == "max_retries_exhausted":
        _emit_retry_exhausted(dto, stop_reason=reason)
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
        log_event(
            logger,
            "worker.job",
            component="queue.persistence",
            status="priority_update_error",
            job_type=job_type,
            entity_id=str(job_id),
            error="invalid_id",
        )
        return False

    with session_scope() as session:
        record = session.get(QueueJob, identifier)
        if record is None or record.type != job_type:
            log_event(
                logger,
                "worker.job",
                component="queue.persistence",
                status="priority_update_error",
                job_type=job_type,
                entity_id=str(job_id),
                error="missing",
            )
            return False

        if record.status not in {
            QueueJobStatus.PENDING.value,
            QueueJobStatus.FAILED.value,
        }:
            log_event(
                logger,
                "worker.job",
                component="queue.persistence",
                status="priority_update_error",
                job_type=job_type,
                entity_id=str(job_id),
                error="invalid_state",
                state=record.status,
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
        dto = _refresh_instance(session, record)
    _emit_worker_job_event(dto, "priority_updated", priority=int(priority))
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


async def enqueue_async(
    job_type: str,
    payload: Mapping[str, Any],
    *,
    priority: int | None = None,
    available_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> QueueJobDTO:
    """Async wrapper around :func:`enqueue` using a worker thread."""

    return await asyncio.to_thread(
        enqueue,
        job_type,
        payload,
        priority=priority,
        available_at=available_at,
        idempotency_key=idempotency_key,
    )


async def fetch_ready_async(job_type: str, *, limit: int = 100) -> List[QueueJobDTO]:
    """Async wrapper around :func:`fetch_ready`."""

    return await asyncio.to_thread(fetch_ready, job_type, limit=limit)


async def lease_async(
    job_id: int,
    *,
    job_type: str,
    lease_seconds: int | None = None,
) -> QueueJobDTO | None:
    """Async wrapper around :func:`lease`."""

    return await asyncio.to_thread(
        lease, job_id, job_type=job_type, lease_seconds=lease_seconds
    )


async def complete_async(
    job_id: int,
    *,
    job_type: str,
    result_payload: Mapping[str, Any] | None = None,
) -> bool:
    """Async wrapper around :func:`complete`."""

    return await asyncio.to_thread(
        complete, job_id, job_type=job_type, result_payload=result_payload
    )


async def fail_async(
    job_id: int,
    *,
    job_type: str,
    error: str | None = None,
    retry_in: int | None = None,
    available_at: datetime | None = None,
    stop_reason: str | None = None,
) -> bool:
    """Async wrapper around :func:`fail`."""

    return await asyncio.to_thread(
        fail,
        job_id,
        job_type=job_type,
        error=error,
        retry_in=retry_in,
        available_at=available_at,
        stop_reason=stop_reason,
    )


async def release_active_leases_async(job_type: str) -> None:
    """Async wrapper around :func:`release_active_leases`."""

    await asyncio.to_thread(release_active_leases, job_type)


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
    "enqueue_async",
    "fetch_ready_async",
    "lease_async",
    "complete_async",
    "fail_async",
    "release_active_leases_async",
]
