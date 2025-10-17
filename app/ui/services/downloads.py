from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module

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

    @staticmethod
    def _to_row(entry: DownloadEntryResponse) -> DownloadRow:
        payload = entry.model_dump()
        progress_value = payload.get("progress")
        progress = float(progress_value) if progress_value is not None else None

        live_metadata = payload.get("live_queue")
        if not isinstance(live_metadata, Mapping):
            live_metadata = None

        return DownloadRow(
            identifier=int(payload["id"]),
            filename=str(payload.get("filename", "")),
            status=str(payload.get("status", "unknown")),
            progress=progress,
            priority=int(payload.get("priority", 0)),
            username=payload.get("username"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            retry_count=int(payload.get("retry_count", 0) or 0),
            next_retry_at=payload.get("next_retry_at"),
            last_error=payload.get("last_error"),
            live_queue=live_metadata,
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
