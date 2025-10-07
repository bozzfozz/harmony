"""Pydantic schemas for the public artist API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReleaseOut(BaseModel):
    """Serialised representation of a persisted artist release."""

    id: int
    artist_key: str
    source: str
    source_id: str | None = None
    title: str
    release_date: date | None = None
    release_type: str | None = None
    total_tracks: int | None = None
    version: str | None = None
    etag: str
    updated_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ArtistOut(BaseModel):
    """Artist metadata enriched with the latest known releases."""

    id: int
    artist_key: str
    source: str
    source_id: str | None = None
    name: str
    genres: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    popularity: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: str
    etag: str
    updated_at: datetime
    created_at: datetime
    releases: List[ReleaseOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class WatchlistItemIn(BaseModel):
    """Input payload for upserting watchlist entries."""

    artist_key: str
    priority: int | None = None
    cooldown_until: datetime | None = None

    @field_validator("artist_key", mode="before")
    @classmethod
    def _normalise_artist_key(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return value


class WatchlistItemOut(BaseModel):
    """Watchlist entry representation."""

    artist_key: str
    priority: int
    last_enqueued_at: datetime | None = None
    cooldown_until: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistPageOut(BaseModel):
    """Paginated watchlist response."""

    items: List[WatchlistItemOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class EnqueueResponse(BaseModel):
    """Response payload returned when scheduling an artist sync."""

    job_id: int
    job_type: str
    status: str
    priority: int
    available_at: datetime
    already_enqueued: bool


__all__ = [
    "ArtistOut",
    "EnqueueResponse",
    "ReleaseOut",
    "WatchlistItemIn",
    "WatchlistItemOut",
    "WatchlistPageOut",
]
