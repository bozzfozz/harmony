"""Dead-letter queue service for listing, requeueing and purging downloads."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Protocol, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.errors import NotFoundError, ValidationAppError
from app.logging import get_logger
from app.models import Download, DownloadState
from app.workers.sync_worker import SyncWorker, _truncate_error

logger = get_logger(__name__)

_DLQ_ENTITY = "download"
_REASON_SANITIZER = re.compile(r"[^a-z0-9]+")


class DLQWorker(Protocol):
    async def enqueue(self, job: Mapping[str, Any]) -> Any:
        """Schedule a job for execution."""


@dataclass(slots=True)
class DLQEntry:
    """A single dead-letter queue entry."""

    id: str
    entity: str
    reason: str
    message: str | None
    created_at: datetime
    updated_at: datetime
    retry_count: int


@dataclass(slots=True)
class DLQListResult:
    """Paginated result set for DLQ listings."""

    items: list[DLQEntry]
    page: int
    page_size: int
    total: int


@dataclass(slots=True)
class DLQRequeueResult:
    """Outcome of a bulk requeue operation."""

    requeued: list[str]
    skipped: list[dict[str, str]]


@dataclass(slots=True)
class DLQPurgeResult:
    """Outcome of a purge operation."""

    purged: int


@dataclass(slots=True)
class DLQStats:
    """Aggregated DLQ statistics."""

    total: int
    by_reason: dict[str, int]
    last_24h: int


class DLQService:
    """Business logic for the dead-letter queue management API."""

    def __init__(
        self,
        *,
        requeue_limit: int = 500,
        purge_limit: int = 1000,
    ) -> None:
        if requeue_limit <= 0:
            raise ValueError("requeue_limit must be positive")
        if purge_limit <= 0:
            raise ValueError("purge_limit must be positive")
        self._requeue_limit = requeue_limit
        self._purge_limit = purge_limit

    def list_entries(
        self,
        session: Session,
        *,
        page: int,
        page_size: int,
        order_by: str,
        order_dir: str,
        reason: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> DLQListResult:
        if page <= 0:
            raise ValidationAppError("page must be >= 1")
        if page_size <= 0:
            raise ValidationAppError("page_size must be >= 1")

        start = time.perf_counter()
        query = self._base_query()
        if created_from is not None:
            query = query.where(Download.created_at >= created_from)
        if created_to is not None:
            query = query.where(Download.created_at <= created_to)
        if reason:
            query = query.where(Download.last_error.ilike(f"%{reason}%"))

        total = session.execute(select(func.count()).select_from(query.subquery())).scalar_one()

        sort_column = Download.created_at if order_by == "created_at" else Download.updated_at
        if order_dir == "asc":
            query = query.order_by(sort_column.asc(), Download.id.asc())
        else:
            query = query.order_by(sort_column.desc(), Download.id.desc())

        offset = (page - 1) * page_size
        rows = session.execute(query.offset(offset).limit(page_size)).scalars().all()
        items = [self._to_entry(row) for row in rows]

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "event=dlq.list page=%d page_size=%d reason=%s from=%s to=%s duration_ms=%.2f",
            page,
            page_size,
            reason or "",
            created_from.isoformat() if created_from else "",
            created_to.isoformat() if created_to else "",
            duration_ms,
        )

        return DLQListResult(items=items, page=page, page_size=page_size, total=int(total))

    async def requeue_bulk(
        self,
        session: Session,
        *,
        ids: Sequence[int],
        worker: "DLQWorker",
        actor: str | None = None,
    ) -> DLQRequeueResult:
        if not ids:
            raise ValidationAppError("ids required (1..%d)" % self._requeue_limit)
        unique_ids = list(dict.fromkeys(ids))
        if len(unique_ids) > self._requeue_limit:
            raise ValidationAppError(f"ids exceed limit of {self._requeue_limit}")

        records = (
            session.execute(select(Download).where(Download.id.in_(unique_ids))).scalars().all()
        )
        found_ids = {record.id for record in records}
        missing = [identifier for identifier in unique_ids if identifier not in found_ids]
        if missing:
            raise NotFoundError("Some downloads were not found")

        now = datetime.utcnow()
        requeue_jobs: list[tuple[int, dict[str, Any]]] = []
        skipped: list[dict[str, str]] = []

        for record in records:
            if record.state != DownloadState.DEAD_LETTER.value:
                reason_label = (
                    "already_queued"
                    if record.state in {"queued", "downloading"}
                    else "not_dead_letter"
                )
                skipped.append({"id": str(record.id), "reason": reason_label})
                continue

            payload = dict(record.request_payload or {})
            file_info = payload.get("file")
            if not isinstance(file_info, dict):
                skipped.append({"id": str(record.id), "reason": "missing_payload"})
                continue
            username = payload.get("username") or record.username
            if not username:
                skipped.append({"id": str(record.id), "reason": "missing_username"})
                continue

            priority = SyncWorker._coerce_priority(
                file_info.get("priority") or payload.get("priority") or record.priority
            )
            file_payload = dict(file_info)
            file_payload["download_id"] = record.id
            file_payload.setdefault("priority", priority)

            payload.update({"file": dict(file_payload), "username": username, "priority": priority})

            record.request_payload = payload
            record.state = DownloadState.QUEUED.value
            record.retry_count = 0
            record.next_retry_at = None
            record.last_error = None
            record.updated_at = now
            session.add(record)

            requeue_jobs.append(
                (
                    record.id,
                    {
                        "username": username,
                        "files": [file_payload],
                        "priority": priority,
                    },
                )
            )

        session.commit()

        requeued_ids: list[str] = []
        start = time.perf_counter()
        for download_id, job in requeue_jobs:
            try:
                await worker.enqueue(job)
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.error(
                    "event=dlq.requeue enqueue_failed id=%s actor=%s error=%s",
                    download_id,
                    actor or "unknown",
                    exc,
                )
                self._restore_dead_letter_state(download_id, str(exc))
                skipped.append({"id": str(download_id), "reason": "enqueue_failed"})
            else:
                requeued_ids.append(str(download_id))

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "event=dlq.requeue actor=%s requeued=%d skipped=%d duration_ms=%.2f",
            actor or "unknown",
            len(requeued_ids),
            len(skipped),
            duration_ms,
        )

        return DLQRequeueResult(requeued=requeued_ids, skipped=skipped)

    def purge_bulk(
        self,
        session: Session,
        *,
        ids: Sequence[int] | None = None,
        older_than: datetime | None = None,
        reason: str | None = None,
        actor: str | None = None,
    ) -> DLQPurgeResult:
        if ids and older_than:
            raise ValidationAppError("ids and older_than are mutually exclusive")
        if not ids and older_than is None:
            raise ValidationAppError("Either ids or older_than must be provided")

        target_ids: list[int]
        if ids:
            unique_ids = list(dict.fromkeys(ids))
            if len(unique_ids) > self._purge_limit:
                raise ValidationAppError(f"ids exceed limit of {self._purge_limit}")
            target_ids = unique_ids
        else:
            query = select(Download.id).where(
                Download.state == DownloadState.DEAD_LETTER.value,
                Download.created_at <= older_than,
            )
            if reason:
                query = query.where(Download.last_error.ilike(f"%{reason}%"))
            query = query.order_by(Download.created_at.asc(), Download.id.asc()).limit(
                self._purge_limit
            )
            target_ids = session.execute(query).scalars().all()

        start = time.perf_counter()

        if not target_ids:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "event=dlq.purge actor=%s purged=0 reason=%s older_than=%s duration_ms=%.2f",
                actor or "unknown",
                reason or "",
                older_than.isoformat() if older_than else "",
                duration_ms,
            )
            return DLQPurgeResult(purged=0)

        deleted = (
            session.query(Download)
            .filter(Download.id.in_(target_ids), Download.state == DownloadState.DEAD_LETTER.value)
            .delete(synchronize_session=False)
        )
        session.commit()

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "event=dlq.purge actor=%s purged=%d reason=%s older_than=%s duration_ms=%.2f",
            actor or "unknown",
            int(deleted),
            reason or "",
            older_than.isoformat() if older_than else "",
            duration_ms,
        )

        return DLQPurgeResult(purged=int(deleted))

    def stats(self, session: Session) -> DLQStats:
        start = time.perf_counter()
        query = self._base_query()
        total = session.execute(select(func.count()).select_from(query.subquery())).scalar_one()

        reason_stmt = (
            select(Download.last_error, func.count(Download.id))
            .where(Download.state == DownloadState.DEAD_LETTER.value)
            .group_by(Download.last_error)
        )
        reason_rows = session.execute(reason_stmt).all()
        by_reason: dict[str, int] = {}
        for last_error, count in reason_rows:
            reason_key = self._normalise_reason(last_error)
            by_reason[reason_key] = by_reason.get(reason_key, 0) + int(count or 0)

        cutoff = datetime.utcnow() - timedelta(hours=24)
        last_24h = session.execute(
            select(func.count(Download.id)).where(
                Download.state == DownloadState.DEAD_LETTER.value,
                Download.created_at >= cutoff,
            )
        ).scalar_one()

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "event=dlq.stats total=%d last_24h=%d distinct_reasons=%d duration_ms=%.2f",
            int(total),
            int(last_24h),
            len(by_reason),
            duration_ms,
        )

        return DLQStats(total=int(total), by_reason=by_reason, last_24h=int(last_24h))

    @staticmethod
    def _base_query() -> Select[tuple[Download]]:
        return select(Download).where(Download.state == DownloadState.DEAD_LETTER.value)

    def _to_entry(self, record: Download) -> DLQEntry:
        return DLQEntry(
            id=str(record.id),
            entity=_DLQ_ENTITY,
            reason=self._normalise_reason(record.last_error),
            message=record.last_error,
            created_at=record.created_at,
            updated_at=record.updated_at,
            retry_count=int(record.retry_count or 0),
        )

    def _normalise_reason(self, value: str | None) -> str:
        if not value:
            return "unknown"
        stripped = value.strip()
        if not stripped:
            return "unknown"
        if ":" in stripped:
            base = stripped.split(":", 1)[0]
        else:
            base = stripped.split()[0]
        slug = _REASON_SANITIZER.sub("_", base.lower()).strip("_")
        return slug or "unknown"

    def _restore_dead_letter_state(self, download_id: int, error: str) -> None:
        truncated = _truncate_error(error)
        now = datetime.utcnow()
        with session_scope() as recovery:
            record = recovery.get(Download, download_id)
            if record is None:
                return
            record.state = DownloadState.DEAD_LETTER.value
            record.last_error = truncated
            record.updated_at = now
            record.next_retry_at = None
            recovery.add(record)
