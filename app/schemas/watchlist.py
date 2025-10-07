"""Pydantic schemas for the watchlist API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WatchlistEntryCreate(BaseModel):
    artist_key: str = Field(..., description="Domain identifier of the artist")
    priority: int = Field(0, description="Scheduling priority (higher runs first)")

    @field_validator("artist_key")
    @classmethod
    def _validate_artist_key(cls, value: str) -> str:
        candidate = (value or "").strip()
        if not candidate:
            raise ValueError("artist_key must not be empty")
        return candidate


class WatchlistPriorityUpdate(BaseModel):
    priority: int = Field(..., description="Updated scheduling priority")


class WatchlistPauseRequest(BaseModel):
    reason: str | None = Field(
        default=None,
        description="Optional note explaining why the artist is paused",
    )
    resume_at: datetime | None = Field(
        default=None,
        description="Optional timestamp describing when to revisit the pause",
    )

    @field_validator("reason")
    @classmethod
    def _normalise_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        return candidate or None


class WatchlistEntryResponse(BaseModel):
    id: int
    artist_key: str
    priority: int
    paused: bool
    pause_reason: str | None = None
    resume_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistListResponse(BaseModel):
    items: list[WatchlistEntryResponse]

