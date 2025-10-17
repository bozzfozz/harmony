from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import Depends, Request

from app.api import watchlist as watchlist_api
from app.dependencies import get_watchlist_service
from app.logging import get_logger
from app.schemas.watchlist import (
    WatchlistEntryCreate,
    WatchlistEntryResponse,
    WatchlistPriorityUpdate,
)
from app.services.watchlist_service import WatchlistService

logger = get_logger(__name__)


@dataclass(slots=True)
class WatchlistRow:
    """Representation of a watchlist entry tailored for UI fragments."""

    artist_key: str
    priority: int
    state_key: str


@dataclass(slots=True)
class WatchlistTable:
    entries: Sequence[WatchlistRow]


class WatchlistUiService:
    """Facade delegating to the watchlist API router for UI consumption."""

    def __init__(self, service: WatchlistService) -> None:
        self._service = service

    def list_entries(self, request: Request) -> WatchlistTable:
        response = watchlist_api.list_watchlist(request=request, service=self._service)
        rows = tuple(self._to_row(item) for item in response.items)
        logger.debug("watchlist.ui.list", extra={"count": len(rows)})
        return WatchlistTable(entries=rows)

    def create_entry(
        self,
        request: Request,
        *,
        artist_key: str,
        priority: int | None = None,
    ) -> WatchlistTable:
        payload = WatchlistEntryCreate(
            artist_key=artist_key,
            priority=priority if priority is not None else 0,
        )
        watchlist_api.create_watchlist_entry(
            payload=payload,
            request=request,
            service=self._service,
        )
        logger.info(
            "watchlist.ui.create",
            extra={"artist_key": artist_key, "priority": payload.priority},
        )
        return self.list_entries(request)

    def update_priority(
        self,
        request: Request,
        *,
        artist_key: str,
        priority: int,
    ) -> WatchlistTable:
        payload = WatchlistPriorityUpdate(priority=priority)
        watchlist_api.update_watchlist_priority(
            artist_key=artist_key,
            payload=payload,
            request=request,
            service=self._service,
        )
        logger.info(
            "watchlist.ui.priority",
            extra={"artist_key": artist_key, "priority": priority},
        )
        return self.list_entries(request)

    @staticmethod
    def _to_row(entry: WatchlistEntryResponse) -> WatchlistRow:
        payload = entry.model_dump()
        paused = bool(payload.get("paused"))
        state_key = "watchlist.state.paused" if paused else "watchlist.state.active"
        return WatchlistRow(
            artist_key=str(payload.get("artist_key", "")),
            priority=int(payload.get("priority", 0)),
            state_key=state_key,
        )


def get_watchlist_ui_service(
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistUiService:
    return WatchlistUiService(service)


__all__ = [
    "WatchlistRow",
    "WatchlistTable",
    "WatchlistUiService",
    "get_watchlist_ui_service",
]
