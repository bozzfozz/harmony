"""Search specific schemas shared across routers and services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.schemas.common import Paging, SourceEnum


class SearchQuery(BaseModel):
    """Payload accepted by the smart search endpoint."""

    model_config = ConfigDict(use_enum_values=True)

    query: str = Field(..., description="Free-text search query")
    type: str = Field(default="mixed", description="Result type filter")
    sources: list[SourceEnum] = Field(
        default_factory=lambda: [SourceEnum.SPOTIFY, SourceEnum.SOULSEEK]
    )
    genre: str | None = None
    year_from: int | None = Field(default=None, ge=1900, le=2099)
    year_to: int | None = Field(default=None, ge=1900, le=2099)
    min_bitrate: int | None = Field(default=None, ge=0)
    format_priority: list[str] | None = None
    limit: int = Field(default=25, ge=1)
    offset: int = Field(default=0, ge=0)

    @field_validator("query")
    @classmethod
    def _ensure_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be empty")
        return stripped

    @field_validator("sources", mode="before")
    @classmethod
    def _normalise_sources(cls, value: Sequence[str] | None) -> list[SourceEnum]:
        if value is None:
            return [SourceEnum.SPOTIFY, SourceEnum.SOULSEEK]

        items: Sequence[str]
        if isinstance(value, str):
            items = [value]
        else:
            items = value

        normalised: list[SourceEnum] = []
        for item in items:
            candidate = str(item).strip().lower()
            if not candidate:
                continue
            try:
                enum_value = SourceEnum(candidate)
            except ValueError:
                continue
            if enum_value not in normalised:
                normalised.append(enum_value)
        return normalised or [SourceEnum.SPOTIFY, SourceEnum.SOULSEEK]

    @field_validator("genre")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("format_priority", mode="before")
    @classmethod
    def _normalise_formats(cls, value: Sequence[str] | None) -> list[str] | None:
        if value is None:
            return None

        items: Sequence[str]
        if isinstance(value, str):
            items = [value]
        else:
            items = value

        formatted: list[str] = []
        for item in items:
            if not item:
                continue
            candidate = str(item).strip().upper()
            if candidate and candidate not in formatted:
                formatted.append(candidate)
        return formatted or None

    @field_validator("year_to")
    @classmethod
    def _validate_year_range(cls, value: int | None, info: ValidationInfo) -> int | None:
        year_from = info.data.get("year_from") if info.data else None
        if year_from is not None and value is not None and year_from > value:
            raise ValueError("year_from must be less than or equal to year_to")
        return value


class SearchItem(BaseModel):
    """Normalised search result entry."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    type: str
    id: str
    source: SourceEnum
    title: str
    artist: str | None = None
    album: str | None = None
    year: int | None = None
    genres: list[str] = Field(default_factory=list)
    bitrate: int | None = None
    score: float | None = Field(default=None, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def _ensure_metadata(cls, value: Mapping[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        return dict(value)


class SearchResponse(BaseModel):
    """Envelope returned by the search endpoint."""

    model_config = ConfigDict(use_enum_values=True)

    items: list[SearchItem]
    paging: Paging
    sources: list[SourceEnum]
    status: str = Field(default="ok")
    failures: dict[str, str] = Field(default_factory=dict)


__all__ = ["SearchItem", "SearchQuery", "SearchResponse"]
