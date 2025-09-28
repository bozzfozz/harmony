"""Utility helpers for download management."""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from app.models import Download
from app.schemas import DownloadEntryResponse
from app.errors import ValidationAppError

STATUS_FILTERS: Dict[str, set[str]] = {
    "running": {"running", "downloading"},
    "in_progress": {"running", "downloading"},
    "queued": {"queued"},
    "pending": {"queued"},
    "completed": {"completed"},
    "failed": {"failed", "dead_letter"},
    "dead_letter": {"dead_letter"},
    "cancelled": {"cancelled"},
}

ACTIVE_STATES = STATUS_FILTERS["running"] | STATUS_FILTERS["queued"]

_FAVOURITE_KEYS = (
    "is_favorite",
    "favorite",
    "liked",
    "is_saved_track",
    "spotify_saved",
    "spotify_like",
)

CSV_HEADERS = [
    "id",
    "filename",
    "status",
    "progress",
    "username",
    "created_at",
    "updated_at",
]


def _normalise_status(value: str) -> str:
    return value.strip().lower()


def resolve_status_filter(value: str) -> set[str]:
    normalised = _normalise_status(value)
    states = STATUS_FILTERS.get(normalised)
    if states is None:
        raise ValidationAppError("Invalid status filter")
    return states


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalised = value.strip().lower()
        return normalised in {"1", "true", "yes", "y"}
    return False


def determine_priority(file_info: MutableMapping[str, Any]) -> int:
    explicit = _coerce_int(file_info.get("priority"))
    if explicit is not None:
        return explicit

    if any(_is_truthy(file_info.get(key)) for key in _FAVOURITE_KEYS):
        return 10

    source = str(file_info.get("source") or "").lower()
    if source in {"spotify_likes", "spotify_saved", "favorites"}:
        return 10

    return 0


def coerce_priority(value: Any) -> Optional[int]:
    return _coerce_int(value)


def serialise_download(download: Download) -> Dict[str, Any]:
    response = DownloadEntryResponse.model_validate(download).model_dump()
    response["username"] = download.username
    response["priority"] = download.priority
    created_at = download.created_at
    updated_at = download.updated_at
    response["created_at"] = created_at.isoformat() if created_at else None
    response["updated_at"] = updated_at.isoformat() if updated_at else None
    return response


def render_downloads_csv(rows: Iterable[Mapping[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_HEADERS)
    writer.writeheader()
    for item in rows:
        writer.writerow(
            {
                "id": item.get("id"),
                "filename": item.get("filename"),
                "status": item.get("status"),
                "progress": item.get("progress"),
                "username": item.get("username"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )
    return buffer.getvalue()
