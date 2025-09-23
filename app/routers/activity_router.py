"""Expose the Harmony activity feed as an API endpoint."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from app.logging import get_logger
from app.utils.activity import activity_manager

router = APIRouter(prefix="/api", tags=["Activity"])
logger = get_logger(__name__)


@router.get("/activity", response_model=list[dict[str, Any]])
def list_activity() -> List[Dict[str, Any]]:
    """Return the most recent activity entries."""

    entries = activity_manager.list()
    logger.debug("Returning %d activity entries", len(entries))
    return entries
