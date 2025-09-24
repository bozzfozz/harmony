"""Expose the Harmony activity feed as an API endpoint."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Query

from app.logging import get_logger
from app.utils.activity import activity_manager

router = APIRouter(prefix="/api", tags=["Activity"])
logger = get_logger(__name__)


@router.get("/activity", response_model=list[dict[str, Any]])
def list_activity(
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)
) -> List[Dict[str, Any]]:
    """Return the most recent activity entries from persistent storage."""

    entries = activity_manager.fetch(limit=limit, offset=offset)
    logger.debug(
        "Returning %d activity entries (limit=%d, offset=%d)",
        len(entries),
        limit,
        offset,
    )
    return entries
