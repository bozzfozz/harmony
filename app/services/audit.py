from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import json
from typing import Any

from sqlalchemy import Select, select

from app.db import session_scope
from app.models import ArtistAuditRecord


def _normalise_scalar(value: Any) -> Any:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return json.loads(json.dumps(value, default=str))


def _normalise_payload(payload: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if payload is None:
        return None
    items = []
    for key, value in payload.items():
        if not isinstance(key, str):
            continue
        items.append((key, _normalise_scalar(value)))
        if len(items) >= 25:
            break
    if not items:
        return None
    return {key: value for key, value in items}


@dataclass(slots=True, frozen=True)
class ArtistAuditRow:
    id: int
    created_at: datetime
    job_id: str | None
    artist_key: str
    entity_type: str
    entity_id: str | None
    event: str
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None


def write_audit(
    *,
    event: str,
    entity_type: str,
    artist_key: str,
    job_id: str | int | None = None,
    entity_id: str | int | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> ArtistAuditRow:
    """Persist an artist audit event and return a lightweight row representation."""

    timestamp = (occurred_at or datetime.utcnow()).replace(tzinfo=None)
    job_value = str(job_id) if job_id is not None else None
    entity_value = str(entity_id) if entity_id is not None else None
    before_payload = _normalise_payload(before)
    after_payload = _normalise_payload(after)

    with session_scope() as session:
        record = ArtistAuditRecord(
            created_at=timestamp,
            job_id=job_value,
            artist_key=artist_key,
            entity_type=entity_type,
            entity_id=entity_value,
            event=event,
            before_json=before_payload,
            after_json=after_payload,
        )
        session.add(record)
        session.flush()
        session.refresh(record)
        return ArtistAuditRow(
            id=int(record.id),
            created_at=record.created_at,
            job_id=record.job_id,
            artist_key=record.artist_key,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            event=record.event,
            before=record.before_json,
            after=record.after_json,
        )


def list_audit_events(
    artist_key: str,
    *,
    limit: int = 100,
    cursor: int | None = None,
) -> tuple[list[ArtistAuditRow], int | None]:
    """Return recent audit events for the provided artist key."""

    key = (artist_key or "").strip()
    if not key:
        return [], None

    try:
        resolved_limit = int(limit)
    except (TypeError, ValueError):
        resolved_limit = 100
    resolved_limit = max(1, min(resolved_limit, 200))

    statement: Select[ArtistAuditRecord] = select(ArtistAuditRecord).where(
        ArtistAuditRecord.artist_key == key
    )
    if cursor is not None:
        try:
            cursor_value = int(cursor)
        except (TypeError, ValueError):
            cursor_value = None
        else:
            statement = statement.where(ArtistAuditRecord.id < cursor_value)

    statement = statement.order_by(ArtistAuditRecord.id.desc()).limit(resolved_limit + 1)

    with session_scope() as session:
        records: Sequence[ArtistAuditRecord] = session.execute(statement).scalars().all()

    next_cursor: int | None = None
    if len(records) > resolved_limit:
        next_cursor = int(records[resolved_limit].id)
        records = records[:resolved_limit]

    rows = [
        ArtistAuditRow(
            id=int(record.id),
            created_at=record.created_at,
            job_id=record.job_id,
            artist_key=record.artist_key,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            event=record.event,
            before=record.before_json,
            after=record.after_json,
        )
        for record in records
    ]
    return rows, next_cursor


__all__ = ["ArtistAuditRow", "write_audit", "list_audit_events"]
