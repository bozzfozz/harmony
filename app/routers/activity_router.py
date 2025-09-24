"""Expose the Harmony activity feed as an API endpoint."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from app.logging import get_logger
from app.utils.activity import activity_manager

router = APIRouter(prefix="/api", tags=["Activity"])
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
