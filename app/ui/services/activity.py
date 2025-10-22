from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.logging import get_logger
from app.utils.activity import activity_manager

logger = get_logger(__name__)


@dataclass(slots=True)
class ActivityPage:
    """Container for a slice of activity entries."""

    items: Sequence[Mapping[str, object]]
    limit: int
    offset: int
    total_count: int
    type_filter: str | None
    status_filter: str | None


class ActivityUiService:
    """Expose activity log entries for UI fragments."""

    def list_activity(
        self,
        *,
        limit: int,
        offset: int,
        type_filter: str | None,
        status_filter: str | None,
    ) -> ActivityPage:
        entries, total_count = activity_manager.fetch(
            limit=limit,
            offset=offset,
            type_filter=type_filter,
            status_filter=status_filter,
        )
        normalized_entries = tuple(dict(entry) for entry in entries)
        logger.debug(
            "activity.ui.page",
            extra={
                "limit": limit,
                "offset": offset,
                "count": len(normalized_entries),
                "type_filter": type_filter,
                "status_filter": status_filter,
            },
        )
        return ActivityPage(
            items=normalized_entries,
            limit=limit,
            offset=offset,
            total_count=total_count,
            type_filter=type_filter,
            status_filter=status_filter,
        )

    async def list_activity_async(
        self,
        *,
        limit: int,
        offset: int,
        type_filter: str | None,
        status_filter: str | None,
    ) -> ActivityPage:
        """Fetch activity entries without blocking the event loop."""

        return await asyncio.to_thread(
            self.list_activity,
            limit=limit,
            offset=offset,
            type_filter=type_filter,
            status_filter=status_filter,
        )


def get_activity_ui_service() -> ActivityUiService:
    """FastAPI dependency returning the activity service instance."""

    return ActivityUiService()


__all__ = ["ActivityPage", "ActivityUiService", "get_activity_ui_service"]
