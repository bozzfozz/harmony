"""Helpers for computing HTTP cache metadata and conditional responses."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from typing import Sequence

from fastapi import Request

from app.models import Playlist


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_PLAYLIST_CACHE_VERSION = "v1"


@dataclass(frozen=True)
class CacheMetadata:
    """Normalized cache metadata for HTTP responses."""

    etag: str
    last_modified: datetime

    def as_headers(self) -> dict[str, str]:
        return {
            "ETag": self.etag,
            "Last-Modified": format_http_datetime(self.last_modified),
        }


def compute_playlist_collection_metadata(
    playlists: Sequence[Playlist],
    *,
    filters_hash: str | None = None,
) -> CacheMetadata:
    """Return deterministic cache metadata for a playlist collection response."""

    normalized = list(playlists)
    resolved_filters = filters_hash or "0"
    if not normalized:
        latest = _EPOCH
        payload = f"playlists|{_PLAYLIST_CACHE_VERSION}|{resolved_filters}|0|{latest.isoformat()}"
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        return CacheMetadata(
            etag=f'"pl-{_PLAYLIST_CACHE_VERSION}-{digest}:0"',
            last_modified=latest,
        )

    latest = _EPOCH
    for playlist in normalized:
        updated_at = _ensure_utc(getattr(playlist, "updated_at", None))
        if updated_at > latest:
            latest = updated_at

    total_count = len(normalized)
    payload = (
        f"playlists|{_PLAYLIST_CACHE_VERSION}|{resolved_filters}|{total_count}|{latest.isoformat()}"
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    etag = f'"pl-{_PLAYLIST_CACHE_VERSION}-{digest}:{total_count}"'
    return CacheMetadata(etag=etag, last_modified=latest)


def format_http_datetime(value: datetime) -> str:
    """Format a datetime instance as an RFC 7231 compliant string."""

    return format_datetime(_ensure_utc(value), usegmt=True)


def is_request_not_modified(
    request: Request,
    *,
    etag: str | None,
    last_modified: datetime | None,
) -> bool:
    """Return ``True`` when the client cache validators match the response metadata."""

    if etag:
        if_none_match = request.headers.get("if-none-match")
        if if_none_match:
            candidates = {token.strip() for token in if_none_match.split(",") if token.strip()}
            if etag in candidates:
                return True

    if last_modified is not None:
        header_value = request.headers.get("if-modified-since")
        if header_value:
            parsed = _parse_http_datetime(header_value)
            if parsed is not None:
                if _ensure_utc(last_modified) <= parsed:
                    return True

    return False


def _ensure_utc(value: datetime | None) -> datetime:
    if value is None:
        return _EPOCH
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_http_datetime(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


__all__ = [
    "CacheMetadata",
    "compute_playlist_collection_metadata",
    "format_http_datetime",
    "is_request_not_modified",
]
