"""Expose the Harmony activity feed as an API endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from typing import Any, Dict, Literal

import csv
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from app.logging import get_logger
from app.db import session_scope
from app.models import ActivityEvent
from app.utils.activity import activity_manager

router = APIRouter(tags=["Activity"])
logger = get_logger(__name__)


@router.get(
    "/activity",
    response_model=dict[str, Any],
)
def list_activity(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    type_filter: str | None = Query(None, alias="type"),
    status_filter: str | None = Query(None, alias="status"),
) -> Dict[str, Any]:
    """Return the most recent activity entries from persistent storage."""

    items, total_count = activity_manager.fetch(
        limit=limit,
        offset=offset,
        type_filter=type_filter,
        status_filter=status_filter,
    )
    logger.debug(
        "Returning %d activity entries (limit=%d, offset=%d, type=%s, status=%s) of %d",
        len(items),
        limit,
        offset,
        type_filter,
        status_filter,
        total_count,
    )
    return {"items": items, "total_count": total_count}


def _normalise_timestamp(value: datetime | None) -> datetime | None:
    """Normalise datetimes to naive UTC for comparisons."""

    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _query_events(
    *,
    type_filter: str | None,
    status_filter: str | None,
    from_timestamp: datetime | None,
    to_timestamp: datetime | None,
    limit: int | None,
) -> list[ActivityEvent]:
    """Fetch activity events directly from the database for exports."""

    filters = []
    if type_filter:
        filters.append(ActivityEvent.type == type_filter)
    if status_filter:
        filters.append(ActivityEvent.status == status_filter)

    start = _normalise_timestamp(from_timestamp)
    end = _normalise_timestamp(to_timestamp)
    if start and end and end < start:
        raise HTTPException(status_code=422, detail="'to' must be greater than or equal to 'from'")
    if start:
        filters.append(ActivityEvent.timestamp >= start)
    if end:
        filters.append(ActivityEvent.timestamp <= end)

    with session_scope() as session:
        query = (
            session.query(ActivityEvent)
            .filter(*filters)
            .order_by(ActivityEvent.timestamp.desc(), ActivityEvent.id.desc())
        )
        if limit is not None:
            query = query.limit(limit)
        return list(query.all())


def _serialise_csv(events: list[ActivityEvent], payload: list[Dict[str, Any]]) -> str:
    """Return CSV content for exported activity events."""

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "timestamp", "type", "status", "details"])

    for event, entry in zip(events, payload):
        details_str = json.dumps(
            entry.get("details", {}), ensure_ascii=False, separators=(",", ":")
        )
        writer.writerow(
            [
                event.id,
                entry.get("timestamp", ""),
                entry.get("type", ""),
                entry.get("status", ""),
                details_str,
            ]
        )

    return buffer.getvalue()


@router.get("/activity/export")
def export_activity_history(
    format: Literal["json", "csv"] = Query("json"),
    type_filter: str | None = Query(None, alias="type"),
    status_filter: str | None = Query(None, alias="status"),
    from_timestamp: datetime | None = Query(None, alias="from"),
    to_timestamp: datetime | None = Query(None, alias="to"),
    limit: int | None = Query(None, ge=1),
) -> Response:
    """Export activity history entries either as JSON or CSV."""

    events = list(
        _query_events(
            type_filter=type_filter,
            status_filter=status_filter,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            limit=limit,
        )
    )
    payload = [activity_manager.serialise_event(event) for event in events]

    if format == "json":
        return JSONResponse(content=payload, media_type="application/json")

    csv_content = _serialise_csv(events, payload)
    today = datetime.utcnow().date().isoformat()
    filename = f"activity_history_{today}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
