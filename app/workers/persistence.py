"""Persistence helpers for the generic `QueueJob` worker queue."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, List, Mapping, Sequence

from sqlalchemy import Select, bindparam, case, func, insert, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

try:  # pragma: no cover - optional dependency guard
    from psycopg.errors import UniqueViolation
except Exception:  # pragma: no cover - fallback for alternative drivers
    UniqueViolation = None  # type: ignore[assignment]

from app.config import settings
from app.db import session_scope
from app.logging import get_logger
from app.logging_events import log_event
from app.models import QueueJob, QueueJobStatus
from app.services.retry_policy_provider import get_retry_policy_provider
from app.utils.idempotency import make_idempotency_key
from app.utils.jsonx import safe_dumps
from app.utils.time import now_utc

LeaseTelemetryHook = Callable[["QueueJobDTO", str, Mapping[str, Any]], None]


logger = get_logger(__name__)
_lease_telemetry_hook: LeaseTelemetryHook | None = None


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
    meta: dict[str, Any] | None = None
    if deduped is not None:
        payload["deduped"] = deduped
        meta = {"dedup": bool(deduped)}
    payload.update({key: value for key, value in extra.items() if value is not None})
    log_event(logger, "worker.job", meta=meta, **payload)


def register_lease_telemetry_hook(
    hook: LeaseTelemetryHook | None,
) -> None:
    """Register a callback that receives lease lifecycle telemetry."""

    global _lease_telemetry_hook
    _lease_telemetry_hook = hook


def _emit_lease_telemetry(
    job: "QueueJobDTO", status: str, *, lease_timeout: int
) -> None:
    if _lease_telemetry_hook is None:
        return

    try:
        _lease_telemetry_hook(
            job,
            status,
            {
                "lease_timeout": int(lease_timeout),
                "priority": int(job.priority),
            },
        )
    except Exception:  # pragma: no cover - defensive hook guard
        logger.exception(
            "Lease telemetry hook raised",
            extra={"event": "queue.lease.telemetry_error"},
        )


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
    provider = get_retry_policy_provider()
    policy = provider.get_retry_policy(job.type)
    bounded_attempt = max(0, min(int(job.attempts), 6))
    base_delay = policy.base_seconds * (2**bounded_attempt)
    meta: dict[str, Any] = {
        "policy_ttl_s": provider.reload_interval,
        "attempt": int(job.attempts),
        "max_attempts": int(policy.max_attempts),
        "backoff_ms": int(base_delay * 1000),
        "jitter_pct": float(policy.jitter_pct),
    }
    if policy.timeout_seconds is not None:
        meta["timeout_s"] = float(policy.timeout_seconds)
    log_event(
        logger,
        "worker.retry_exhausted",
        component="queue.persistence",
        entity_id=str(job.id),
        job_type=job.type,
        status="retry_exhausted",
        stop_reason=stop_reason,
        attempts=int(job.attempts),
        meta=meta,
    )


def _resolve_priority(payload: Mapping[str, Any]) -> int:
    priority_value = payload.get("priority", 0)
    try:
        parsed = int(priority_value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _resolve_visibility_timeout(
    payload: Mapping[str, Any], override: int | None = None
) -> int:
    if override is not None:
        try:
            resolved_override = int(override)
        except (TypeError, ValueError):
            resolved_override = 0
        return max(5, resolved_override)

    payload_value = payload.get("visibility_timeout")
    from app.dependencies import (
        get_app_config,  # lazy import to avoid circular dependency
    )

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
        return make_idempotency_key(job_type, serialised)

    if isinstance(candidate, str):
        return candidate

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
        result_payload=(
            dict(record.result_payload or {}) if record.result_payload else None
        ),
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
    scheduled_for: datetime | None,
) -> tuple[QueueJob, bool]:
    """Insert or update a queue job guarded by the idempotency key."""

    bind = session.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "") if bind else ""

    stmt_base: Select[QueueJob] = select(QueueJob).where(
        QueueJob.idempotency_key == dedupe_key
    )

    def _log_dedupe() -> None:
        logger.debug(
            "Queue job dedupe hit",
            extra={
                "event": "queue.job.dedupe",
                "job_type": job_type,
                "idempotency_key": dedupe_key,
                "dialect": dialect_name or "unknown",
            },
        )

    if dialect_name != "postgresql":
        logger.error(
            "Queue job persistence now requires PostgreSQL",  # pragma: no cover - guard rail
            extra={
                "event": "queue.job.unsupported_dialect",
                "idempotency_key": dedupe_key,
                "dialect": dialect_name or "unknown",
            },
        )
        raise RuntimeError("Queue job persistence requires PostgreSQL")

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    available_value: Any = scheduled_for if scheduled_for is not None else func.now()
    now_value = func.now()
    insert_stmt = pg_insert(QueueJob).values(
        type=job_type,
        payload=dict(payload),
        priority=priority,
        available_at=available_value,
        idempotency_key=dedupe_key,
        status=QueueJobStatus.PENDING.value,
        stop_reason=None,
        lease_expires_at=None,
        last_error=None,
        result_payload=None,
        attempts=0,
        created_at=now_value,
        updated_at=now_value,
    )
    excluded = insert_stmt.excluded
    update_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["idempotency_key"],
        set_={
            "payload": excluded.payload,
            "priority": excluded.priority,
            "available_at": excluded.available_at,
            "status": QueueJobStatus.PENDING.value,
            "stop_reason": None,
            "lease_expires_at": None,
            "last_error": None,
            "result_payload": None,
            "updated_at": now_value,
            "attempts": case(
                (
                    QueueJob.status.in_(
                        [
                            QueueJobStatus.COMPLETED.value,
                            QueueJobStatus.CANCELLED.value,
                        ]
                    ),
                    0,
                ),
                else_=QueueJob.attempts,
            ),
        },
        where=(QueueJob.type == job_type),
    ).returning(QueueJob.id, text("xmax = 0").label("inserted"))

    try:
        result = session.execute(update_stmt)
    except IntegrityError as exc:
        original = getattr(exc, "orig", exc)
        if UniqueViolation is not None and isinstance(original, UniqueViolation):
            existing = session.execute(stmt_base).scalars().first()
            if existing is None:
                raise
            _log_dedupe()
            return existing, True
        raise

    row = result.first()
    if row is None:
        existing = session.execute(stmt_base).scalars().first()
        if existing is None:
            raise RuntimeError("Queue job upsert conflict without existing record")
        if existing.type != job_type:
            logger.warning(
                "Queue job idempotency key reused by different job type",
                extra={
                    "event": "queue.job.dedupe_conflict",
                    "requested_type": job_type,
                    "existing_type": existing.type,
                    "idempotency_key": dedupe_key,
                    "dialect": dialect_name or "unknown",
                },
            )
        _log_dedupe()
        return existing, True

    record = session.get(QueueJob, row.id)
    if record is None:
        raise RuntimeError("Queue job record missing after upsert")

    deduped = not bool(row.inserted)
    if deduped:
        _log_dedupe()
    return record, deduped


def enqueue(
    job_type: str,
    payload: Mapping[str, Any],
    *,
    priority: int | None = None,
    available_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> QueueJobDTO:
    """Insert a new queue job or upsert by idempotency key."""

    scheduled_for = available_at
    payload_dict = dict(payload)
    dedupe_key = idempotency_key or _derive_idempotency_key(job_type, payload_dict)
    resolved_priority = (
        priority if priority is not None else _resolve_priority(payload_dict)
    )

    with session_scope() as session:
        if dedupe_key:
            record, deduped = _upsert_queue_job(
                session,
                job_type=job_type,
                dedupe_key=dedupe_key,
                payload=payload_dict,
                priority=resolved_priority,
                scheduled_for=scheduled_for,
            )
        else:
            now_expr = func.now()
            insert_stmt = (
                insert(QueueJob)
                .values(
                    type=job_type,
                    payload=payload_dict,
                    priority=resolved_priority,
                    available_at=scheduled_for or now_expr,
                    idempotency_key=None,
                    status=QueueJobStatus.PENDING.value,
                    stop_reason=None,
                    lease_expires_at=None,
                    last_error=None,
                    result_payload=None,
                    attempts=0,
                    created_at=now_expr,
                    updated_at=now_expr,
                )
                .returning(QueueJob.id)
            )
            result = session.execute(insert_stmt)
            inserted_id = result.scalar_one()
            record = session.get(QueueJob, inserted_id)
            if record is None:
                raise RuntimeError("Queue job record missing after insert")
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


def _release_expired_leases(session: Session, job_type: str) -> bool:
    now_expr = func.now()
    stmt = (
        update(QueueJob)
        .where(
            QueueJob.type == job_type,
            QueueJob.status == QueueJobStatus.LEASED.value,
            QueueJob.lease_expires_at.is_not(None),
            QueueJob.lease_expires_at <= now_expr,
        )
        .values(
            status=QueueJobStatus.PENDING.value,
            lease_expires_at=None,
            available_at=now_expr,
            updated_at=now_expr,
        )
    )
    result = session.execute(stmt)
    return bool(result.rowcount)


def fetch_ready(job_type: str, *, limit: int = 100) -> List[QueueJobDTO]:
    """Return queue jobs ready for processing (expired leases are reset)."""

    with session_scope() as session:
        stmt: Select[QueueJob] = (
            select(QueueJob)
            .where(
                QueueJob.type == job_type,
                QueueJob.status == QueueJobStatus.PENDING.value,
                QueueJob.available_at <= func.now(),
            )
            .order_by(
                QueueJob.priority.desc(),
                QueueJob.available_at.asc(),
                QueueJob.id.asc(),
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        _release_expired_leases(session, job_type)
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

    with session_scope() as session:
        stmt = (
            select(QueueJob)
            .where(
                QueueJob.id == job_id,
                QueueJob.type == job_type,
                QueueJob.status == QueueJobStatus.PENDING.value,
                QueueJob.available_at <= func.now(),
                or_(
                    QueueJob.lease_expires_at.is_(None),
                    QueueJob.lease_expires_at <= func.now(),
                ),
            )
            .with_for_update(skip_locked=True)
        )
        record = session.execute(stmt).scalars().first()
        if record is None:
            return None

        timeout = _resolve_visibility_timeout(record.payload or {}, lease_seconds)
        lease_interval = func.make_interval(secs=bindparam("lease_timeout"))
        now_expr = func.now()
        update_stmt = (
            update(QueueJob)
            .where(
                QueueJob.id == job_id,
                QueueJob.type == job_type,
                QueueJob.status == QueueJobStatus.PENDING.value,
                QueueJob.available_at <= func.now(),
                or_(
                    QueueJob.lease_expires_at.is_(None),
                    QueueJob.lease_expires_at <= func.now(),
                ),
            )
            .values(
                status=QueueJobStatus.LEASED.value,
                attempts=QueueJob.attempts + 1,
                lease_expires_at=now_expr + lease_interval,
                updated_at=now_expr,
            )
            .returning(QueueJob.id)
        )
        result = session.execute(update_stmt, {"lease_timeout": int(timeout)})
        if not result.rowcount:
            return None

        session.flush()
        session.refresh(record)
        dto = _to_dto(record)
    _emit_worker_job_event(dto, "leased", lease_timeout_s=timeout)
    _emit_lease_telemetry(dto, "leased", lease_timeout=timeout)
    return dto


def heartbeat(
    job_id: int,
    *,
    job_type: str,
    lease_seconds: int | None = None,
) -> bool:
    """Extend the lease for an in-progress job."""

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

        timeout = _resolve_visibility_timeout(record.payload or {}, lease_seconds)
        update_stmt = (
            update(QueueJob)
            .where(
                QueueJob.id == job_id,
                QueueJob.type == job_type,
                QueueJob.status == QueueJobStatus.LEASED.value,
                QueueJob.lease_expires_at.is_not(None),
                QueueJob.lease_expires_at > func.now(),
            )
            .values(
                lease_expires_at=func.now()
                + func.make_interval(secs=bindparam("lease_timeout")),
                updated_at=func.now(),
            )
        )
        result = session.execute(update_stmt, {"lease_timeout": int(timeout)})
        if result.rowcount:
            session.flush()
            session.refresh(record)
            dto = _to_dto(record)
            _emit_lease_telemetry(dto, "heartbeat", lease_timeout=timeout)
            return True
        return False


def complete(
    job_id: int,
    *,
    job_type: str,
    result_payload: Mapping[str, Any] | None = None,
) -> bool:
    """Mark a leased job as completed."""

    dto: QueueJobDTO | None = None
    with session_scope() as session:
        payload_value = dict(result_payload or {}) or None
        update_stmt = (
            update(QueueJob)
            .where(
                QueueJob.id == job_id,
                QueueJob.type == job_type,
            )
            .values(
                status=QueueJobStatus.COMPLETED.value,
                lease_expires_at=None,
                last_error=None,
                result_payload=payload_value,
                stop_reason=None,
                updated_at=func.now(),
            )
            .returning(QueueJob)
        )
        record = session.execute(update_stmt).scalars().first()
        if record is None:
            return False
        dto = _to_dto(record)
    if dto is None:
        raise RuntimeError("Queue job refresh failed after completion.")
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

    with session_scope() as session:
        now_expr = func.now()
        params: dict[str, Any] = {}
        values: dict[str, Any] = {
            "last_error": error,
            "updated_at": now_expr,
            "lease_expires_at": None,
        }

        if retry_in is not None or available_at is not None:
            values["status"] = QueueJobStatus.PENDING.value
            values["stop_reason"] = None
            if available_at is not None:
                values["available_at"] = available_at
            else:
                values["available_at"] = now_expr + func.make_interval(
                    secs=bindparam("retry_delay")
                )
                params["retry_delay"] = max(0, int(retry_in or 0))
        else:
            values["status"] = QueueJobStatus.FAILED.value
            values["stop_reason"] = stop_reason

        update_stmt = (
            update(QueueJob)
            .where(
                QueueJob.id == job_id,
                QueueJob.type == job_type,
            )
            .values(**values)
        )
        execution_params = params if params else None
        if execution_params is None:
            result = session.execute(update_stmt)
        else:
            result = session.execute(update_stmt, execution_params)
        return bool(result.rowcount)


def to_dlq(
    job_id: int,
    *,
    job_type: str,
    reason: str,
    payload: Mapping[str, Any] | None = None,
) -> bool:
    """Move a job to the dead-letter queue state."""

    dto: QueueJobDTO | None = None
    with session_scope() as session:
        payload_value = dict(payload or {}) or None
        update_stmt = (
            update(QueueJob)
            .where(
                QueueJob.id == job_id,
                QueueJob.type == job_type,
            )
            .values(
                status=QueueJobStatus.CANCELLED.value,
                lease_expires_at=None,
                last_error=reason,
                result_payload=payload_value,
                stop_reason=reason,
                updated_at=func.now(),
            )
            .returning(QueueJob)
        )
        record = session.execute(update_stmt).scalars().first()
        if record is None:
            return False
        dto = _to_dto(record)
    if dto is None:
        raise RuntimeError(
            "Queue job refresh failed after moving to dead-letter queue."
        )
    _emit_worker_job_event(dto, "dead_letter", stop_reason=reason)
    if reason == "max_retries_exhausted":
        _emit_retry_exhausted(dto, stop_reason=reason)
    return True


def release_active_leases(job_type: str) -> None:
    """Release all leases for a job type regardless of expiry."""

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
                updated_at=func.now(),
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
    "register_lease_telemetry_hook",
]
