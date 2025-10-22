from __future__ import annotations

import asyncio

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from typing import Any

from fastapi import Depends

from app.dependencies import get_download_service
from app.logging import get_logger
from app.schemas import DownloadEntryResponse, DownloadPriorityUpdate
from app.services.download_service import DownloadService

logger = get_logger(__name__)


@dataclass(slots=True)
class DownloadRow:
    """Lightweight representation of a download entry for UI rendering."""

    identifier: int
    filename: str
    status: str
    progress: float | None
    priority: int
    username: str | None
    created_at: datetime | None
    updated_at: datetime | None
    retry_count: int = 0
    next_retry_at: datetime | None = None
    last_error: str | None = None
    live_queue: Mapping[str, Any] | None = None
    organized_path: str | None = None
    lyrics_status: str | None = None
    has_lyrics: bool | None = None
    lyrics_path: str | None = None
    artwork_status: str | None = None
    has_artwork: bool | None = None
    artwork_path: str | None = None
    spotify_track_id: str | None = None
    spotify_album_id: str | None = None


@dataclass(slots=True)
class DownloadPage:
    """Container for a downloads table page including pagination metadata."""

    items: Sequence[DownloadRow]
    limit: int
    offset: int
    has_next: bool
    has_previous: bool


class DownloadsUiService:
    """Adapter translating download router payloads into UI-friendly structures."""

    def __init__(self, service: DownloadService) -> None:
        self._service = service

    def list_downloads(
        self,
        *,
        limit: int,
        offset: int,
        include_all: bool,
        status_filter: str | None,
    ) -> DownloadPage:
        download_router = import_module("app.routers.download_router")
        response = download_router.list_downloads(
            limit=limit,
            offset=offset,
            all=include_all,
            status_filter=status_filter,
            service=self._service,
        )
        rows = tuple(self._to_row(entry) for entry in response.downloads)

        probe_offset = offset + limit
        next_response = download_router.list_downloads(
            limit=1,
            offset=probe_offset,
            all=include_all,
            status_filter=status_filter,
            service=self._service,
        )
        has_next = bool(next_response.downloads)
        has_previous = offset > 0

        logger.debug(
            "downloads.ui.page",
            extra={
                "limit": limit,
                "offset": offset,
                "count": len(rows),
                "status_filter": status_filter,
                "include_all": include_all,
                "has_next": has_next,
            },
        )
        return DownloadPage(
            items=rows,
            limit=limit,
            offset=offset,
            has_next=has_next,
            has_previous=has_previous,
        )

    async def list_downloads_async(
        self,
        *,
        limit: int,
        offset: int,
        include_all: bool,
        status_filter: str | None,
    ) -> DownloadPage:
        """Run :meth:`list_downloads` in a background executor."""

        return await asyncio.to_thread(
            self.list_downloads,
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=status_filter,
        )

    def update_priority(self, *, download_id: int, priority: int) -> DownloadRow:
        payload = DownloadPriorityUpdate(priority=priority)
        download_router = import_module("app.routers.download_router")
        updated = download_router.update_download_priority(
            download_id=download_id,
            payload=payload,
            service=self._service,
        )
        logger.info(
            "downloads.ui.priority",
            extra={
                "download_id": download_id,
                "priority": priority,
            },
        )
        return self._to_row(updated)

    async def retry_download(
        self,
        *,
        download_id: int,
        limit: int,
        offset: int,
        include_all: bool,
        status_filter: str | None,
    ) -> DownloadPage:
        """Retry a download and return the refreshed page payload."""

        download_router = import_module("app.routers.download_router")
        await download_router.retry_download(
            download_id=download_id,
            service=self._service,
        )
        logger.info(
            "downloads.ui.retry",
            extra={
                "download_id": download_id,
                "limit": limit,
                "offset": offset,
                "include_all": include_all,
                "status_filter": status_filter,
            },
        )
        return await self.list_downloads_async(
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=status_filter,
        )

    async def cancel_download(
        self,
        *,
        download_id: int,
        limit: int,
        offset: int,
        include_all: bool,
        status_filter: str | None,
    ) -> DownloadPage:
        """Cancel a download and return refreshed table data."""

        download_router = import_module("app.routers.download_router")
        await download_router.cancel_download(
            download_id=download_id,
            service=self._service,
        )
        logger.info(
            "downloads.ui.cancel",
            extra={
                "download_id": download_id,
                "limit": limit,
                "offset": offset,
                "include_all": include_all,
                "status_filter": status_filter,
            },
        )
        return await self.list_downloads_async(
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=status_filter,
        )

    def export_downloads(
        self,
        *,
        format: str,
        status_filter: str | None,
        from_time: str | None = None,
        to_time: str | None = None,
    ) -> Any:
        """Delegate download exports to the router and return the response."""

        download_router = import_module("app.routers.download_router")
        logger.info(
            "downloads.ui.export",
            extra={
                "format": format,
                "status_filter": status_filter,
                "from": from_time,
                "to": to_time,
            },
        )
        return download_router.export_downloads(
            format=format,
            status_filter=status_filter,
            from_time=from_time,
            to_time=to_time,
            service=self._service,
        )

    @staticmethod
    def _to_row(entry: DownloadEntryResponse) -> DownloadRow:
        progress_value = entry.progress
        progress: float | None
        if progress_value is None:
            progress = None
        else:
            numeric = float(progress_value)
            if numeric > 1.0:
                numeric /= 100.0
            progress = max(0.0, min(numeric, 1.0))

        live_metadata = entry.live_queue if isinstance(entry.live_queue, Mapping) else None

        return DownloadRow(
            identifier=int(entry.id),
            filename=str(entry.filename or ""),
            status=str(entry.status or "unknown"),
            progress=progress,
            priority=int(entry.priority or 0),
            username=entry.username,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            retry_count=int(entry.retry_count or 0),
            next_retry_at=entry.next_retry_at,
            last_error=entry.last_error,
            live_queue=live_metadata,
            organized_path=entry.organized_path,
            lyrics_status=entry.lyrics_status,
            has_lyrics=entry.has_lyrics,
            lyrics_path=entry.lyrics_path,
            artwork_status=entry.artwork_status,
            has_artwork=entry.has_artwork,
            artwork_path=entry.artwork_path,
            spotify_track_id=entry.spotify_track_id,
            spotify_album_id=entry.spotify_album_id,
        )


def get_downloads_ui_service(
    service: DownloadService = Depends(get_download_service),
) -> DownloadsUiService:
    """FastAPI dependency producing a :class:`DownloadsUiService` instance."""

    return DownloadsUiService(service)


__all__ = [
    "DownloadRow",
    "DownloadPage",
    "DownloadsUiService",
    "get_downloads_ui_service",
]
