"""Canonical provider DTO definitions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ID, URI, ISODateTime


class ProviderArtist(BaseModel):
    """Artist metadata normalised across providers."""

    model_config = ConfigDict(frozen=True)

    id: ID | None = None
    name: str
    uri: URI | None = None
    genres: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _ensure_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("artist name must not be empty")
        return stripped


class ProviderAlbum(BaseModel):
    """Album metadata normalised across providers."""

    model_config = ConfigDict(frozen=True)

    id: ID | None = None
    name: str
    uri: URI | None = None
    artists: list[ProviderArtist] = Field(default_factory=list)
    release_date: ISODateTime | None = None
    total_tracks: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _ensure_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("album name must not be empty")
        return stripped


class ProviderTrack(BaseModel):
    """Track metadata enriched with optional candidates."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: ID | None = None
    name: str
    provider: str
    uri: URI | None = None
    artists: list[ProviderArtist] = Field(default_factory=list)
    album: ProviderAlbum | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    isrc: str | None = None
    score: float | None = Field(default=None, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "provider")
    @classmethod
    def _ensure_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


__all__ = ["ProviderAlbum", "ProviderArtist", "ProviderTrack"]
