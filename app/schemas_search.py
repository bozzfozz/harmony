"""Pydantic models for the unified search endpoint."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

SourceLiteral = Literal["spotify", "soulseek"]
ItemTypeLiteral = Literal["track", "album", "artist"]
SearchTypeLiteral = Literal["track", "album", "artist", "mixed"]


class SearchRequest(BaseModel):
    """Schema describing the smart search payload."""

    query: str = Field(..., description="Free-text search query")
    type: SearchTypeLiteral = Field(
        default="mixed", description="Result type filter (artist/album/track/mixed)"
    )
    sources: list[SourceLiteral] = Field(
        default_factory=lambda: ["spotify", "soulseek"],
        description="Sources to query",
    )
    genre: str | None = Field(
        default=None,
        description="Optional genre filter (case-insensitive, diacritic agnostic)",
    )
    year_from: int | None = Field(
        default=None,
        ge=1900,
        le=2099,
        description="Lower bound of the release year (inclusive)",
    )
    year_to: int | None = Field(
        default=None,
        ge=1900,
        le=2099,
        description="Upper bound of the release year (inclusive)",
    )
    min_bitrate: int | None = Field(
        default=None, ge=0, description="Minimum acceptable bitrate in kbps"
    )
    format_priority: list[str] | None = Field(
        default=None,
        description="Preferred audio formats used for secondary sorting",
    )
    limit: int = Field(default=25, ge=1, description="Maximum number of items to return")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")

    @field_validator("query")
    @classmethod
    def _ensure_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Query must not be empty")
        return stripped

    @field_validator("sources", mode="before")
    @classmethod
    def _normalise_sources(cls, value: Sequence[str] | None) -> list[SourceLiteral]:
        if value in (None, "", []):
            return ["spotify", "soulseek"]
        normalised: list[SourceLiteral] = []
        for entry in value:
            if not entry:
                continue
            lowered = str(entry).strip().lower()
            if lowered in {"spotify", "soulseek"} and lowered not in normalised:
                normalised.append(lowered)  # type: ignore[arg-type]
        return normalised or ["spotify", "soulseek"]

    @field_validator("genre")
    @classmethod
    def _strip_genre(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("format_priority", mode="before")
    @classmethod
    def _normalise_formats(cls, value: Sequence[str] | None) -> list[str] | None:
        if value in (None, ""):
            return None
        normalised: list[str] = []
        for entry in value:
            if not entry:
                continue
            formatted = str(entry).strip()
            if not formatted:
                continue
            normalised.append(formatted.upper())
        seen: set[str] = set()
        ordered: list[str] = []
        for item in normalised:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered or None

    @field_validator("year_to")
    @classmethod
    def _validate_year_range(cls, year_to: int | None, info: ValidationInfo) -> int | None:
        year_from = info.data.get("year_from") if info.data else None
        if year_from is not None and year_to is not None and year_from > year_to:
            raise ValueError("year_from must be less than or equal to year_to")
        return year_to


class SearchItem(BaseModel):
    """Normalised search result entry."""

    type: ItemTypeLiteral
    id: str
    source: SourceLiteral
    title: str
    artist: str | None = None
    album: str | None = None
    year: int | None = None
    genres: list[str] = Field(default_factory=list)
    bitrate: int | None = None
    format: str | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def _ensure_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        return value


class SearchResponse(BaseModel):
    """Envelope returned by the smart search endpoint."""

    ok: bool = True
    total: int
    limit: int
    offset: int
    items: list[SearchItem]
