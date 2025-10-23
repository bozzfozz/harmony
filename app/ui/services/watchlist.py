from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Request

from app.api import watchlist as watchlist_api
from app.dependencies import get_watchlist_service
from app.logging import get_logger
from app.schemas.watchlist import (
    WatchlistEntryCreate,
    WatchlistEntryResponse,
    WatchlistPauseRequest,
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
    paused: bool = False


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

    async def list_entries_async(self, request: Request) -> WatchlistTable:
        """Asynchronous wrapper for ``list_entries`` using a worker thread."""

        def _run() -> WatchlistTable:
            return self.list_entries(request)

        return await asyncio.to_thread(_run)

    async def create_entry(
        self,
        request: Request,
        *,
        artist_key: str,
        priority: int | None = None,
        pause_reason: str | None = None,
        resume_at: datetime | None = None,
    ) -> WatchlistTable:
        payload = WatchlistEntryCreate(
            artist_key=artist_key,
            priority=priority if priority is not None else 0,
        )

        pause_requested = pause_reason is not None or resume_at is not None

        def _run() -> None:
            watchlist_api.create_watchlist_entry(
                payload=payload,
                request=request,
                service=self._service,
            )

        await asyncio.to_thread(_run)
        logger.info(
            "watchlist.ui.create",
            extra={
                "artist_key": artist_key,
                "priority": payload.priority,
                "pause_requested": pause_requested,
            },
        )
        if pause_requested:
            return await self.pause_entry(
                request,
                artist_key=artist_key,
                reason=pause_reason,
                resume_at=resume_at,
            )
        return await self.list_entries_async(request)

    async def update_priority(
        self,
        request: Request,
        *,
        artist_key: str,
        priority: int,
    ) -> WatchlistTable:
        payload = WatchlistPriorityUpdate(priority=priority)

        def _run() -> None:
            watchlist_api.update_watchlist_priority(
                artist_key=artist_key,
                payload=payload,
                request=request,
                service=self._service,
            )

        await asyncio.to_thread(_run)
        logger.info(
            "watchlist.ui.priority",
            extra={"artist_key": artist_key, "priority": priority},
        )
        return await self.list_entries_async(request)

    async def pause_entry(
        self,
        request: Request,
        *,
        artist_key: str,
        reason: str | None = None,
        resume_at: datetime | None = None,
    ) -> WatchlistTable:
        payload = WatchlistPauseRequest(reason=reason, resume_at=resume_at)

        def _run() -> WatchlistTable:
            watchlist_api.pause_watchlist_entry(
                artist_key=artist_key,
                payload=payload,
                request=request,
                service=self._service,
            )
            logger.info(
                "watchlist.ui.pause",
                extra={
                    "artist_key": artist_key,
                    "has_reason": bool(payload.reason),
                    "resume_at": payload.resume_at.isoformat() if payload.resume_at else None,
                },
            )
            return self.list_entries(request)

        return await asyncio.to_thread(_run)

    async def resume_entry(self, request: Request, *, artist_key: str) -> WatchlistTable:
        def _run() -> WatchlistTable:
            watchlist_api.resume_watchlist_entry(
                artist_key=artist_key,
                request=request,
                service=self._service,
            )
            logger.info("watchlist.ui.resume", extra={"artist_key": artist_key})
            return self.list_entries(request)

        return await asyncio.to_thread(_run)

    async def delete_entry(self, request: Request, *, artist_key: str) -> WatchlistTable:
        def _run() -> WatchlistTable:
            watchlist_api.delete_watchlist_entry(
                artist_key=artist_key,
                request=request,
                service=self._service,
            )
            logger.info("watchlist.ui.delete", extra={"artist_key": artist_key})
            return self.list_entries(request)

        return await asyncio.to_thread(_run)

    @staticmethod
    def _to_row(entry: WatchlistEntryResponse) -> WatchlistRow:
        payload = entry.model_dump()
        paused = bool(payload.get("paused"))
        state_key = "watchlist.state.paused" if paused else "watchlist.state.active"
        return WatchlistRow(
            artist_key=str(payload.get("artist_key", "")),
            priority=int(payload.get("priority", 0)),
            state_key=state_key,
            paused=paused,
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
