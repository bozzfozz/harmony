"""Pydantic models for the unified search endpoint."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator


SourceLiteral = Literal["spotify", "plex", "soulseek"]
ItemTypeLiteral = Literal["track", "album", "artist"]
SortByLiteral = Literal["relevance", "bitrate", "year", "duration"]
SortOrderLiteral = Literal["asc", "desc"]


class SearchFilters(BaseModel):
    """Filter options that may be applied to search results."""

    types: Optional[List[ItemTypeLiteral]] = Field(
        default=None,
        description="Restrict results to specific item types.",
    )
    genres: Optional[List[str]] = Field(
        default=None, description="One or more genres to match (case-insensitive)."
    )
    year_range: Optional[Tuple[Optional[int], Optional[int]]] = Field(
        default=None,
        description="Inclusive year range, expressed as [min, max].",
    )
    duration_ms: Optional[Tuple[Optional[int], Optional[int]]] = Field(
        default=None,
        description="Inclusive duration range in milliseconds.",
    )
    explicit: Optional[bool] = Field(
        default=None,
        description="Whether to include only explicit or clean tracks (Spotify only).",
    )
    min_bitrate: Optional[int] = Field(
        default=None, ge=0, description="Minimum accepted bitrate in kbps."
    )
    preferred_formats: Optional[List[str]] = Field(
        default=None,
        description="Preferred audio file formats (used to boost relevance).",
    )
    username: Optional[str] = Field(
        default=None,
        description="Restrict Soulseek matches to a specific username.",
    )

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("types", mode="before")
    @classmethod
    def _normalise_types(cls, value: Optional[Sequence[str]]) -> Optional[List[ItemTypeLiteral]]:
        if value in (None, "", []):
            return None
        filtered: list[ItemTypeLiteral] = []
        for entry in value:
            if not entry:
                continue
            lowered = str(entry).strip().lower()
            if lowered in {"track", "album", "artist"}:
                filtered.append(lowered)  # type: ignore[arg-type]
        return filtered or None

    @field_validator("genres", "preferred_formats", mode="before")
    @classmethod
    def _normalise_list(cls, value: Optional[Sequence[str]]) -> Optional[List[str]]:
        if value in (None, ""):
            return None
        normalised = [str(item).strip() for item in value if str(item).strip()]
        return normalised or None

    @field_validator("year_range", "duration_ms", mode="before")
    @classmethod
    def _validate_range(
        cls, value: Optional[Sequence[Optional[int]]]
    ) -> Optional[Tuple[Optional[int], Optional[int]]]:
        if value in (None, ""):
            return None
        if not isinstance(value, Sequence) or len(value) != 2:
            raise ValueError("Range filters must contain exactly two values")
        start_raw, end_raw = value[0], value[1]
        start = int(start_raw) if start_raw not in {None, ""} else None
        end = int(end_raw) if end_raw not in {None, ""} else None
        if start is not None and end is not None and start > end:
            raise ValueError("Range start must be less than or equal to range end")
        return (start, end)

    @field_validator("username")
    @classmethod
    def _strip_username(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class SearchSort(BaseModel):
    """Sorting configuration for search results."""

    by: SortByLiteral = Field(default="relevance")
    order: SortOrderLiteral = Field(default="desc")


class SearchPagination(BaseModel):
    """Pagination options for the search endpoint."""

    page: int = Field(default=1, ge=1)
    size: int = Field(default=25, ge=1, le=100)


class SearchRequest(BaseModel):
    """Incoming payload for the unified search endpoint."""

    query: str = Field(..., description="Free-text search query.")
    sources: Optional[List[SourceLiteral]] = Field(
        default=None,
        description="Explicit set of sources to query. Defaults to all sources.",
    )
    filters: SearchFilters = Field(default_factory=SearchFilters)
    sort: SearchSort = Field(default_factory=SearchSort)
    pagination: SearchPagination = Field(default_factory=SearchPagination)

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Query must not be empty")
        return stripped

    @field_validator("sources", mode="before")
    @classmethod
    def _normalise_sources(cls, value: Optional[Sequence[str]]) -> Optional[List[SourceLiteral]]:
        if value in (None, "", []):
            return None
        normalised: list[SourceLiteral] = []
        for entry in value:
            if not entry:
                continue
            lowered = str(entry).strip().lower()
            if lowered in {"spotify", "plex", "soulseek"}:
                normalised.append(lowered)  # type: ignore[arg-type]
        return normalised or None


class SearchItem(BaseModel):
    """Normalised search item returned by the unified search endpoint."""

    id: str
    type: ItemTypeLiteral
    source: SourceLiteral
    title: str
    artists: List[str] = Field(default_factory=list)
    album: Optional[str] = None
    year: Optional[int] = None
    duration_ms: Optional[int] = None
    bitrate: Optional[int] = None
    format: Optional[str] = None
    explicit: Optional[bool] = None
    score: float = 0.0
    genres: List[str] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("score")
    @classmethod
    def _clamp_score(cls, value: float) -> float:
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return round(value, 4)


class SearchResponse(BaseModel):
    """Response envelope for the unified search endpoint."""

    page: int
    size: int
    total: int
    items: List[SearchItem]
    errors: Optional[Dict[str, str]] = None
