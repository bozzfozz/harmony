"""Canonical provider DTO definitions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ID, URI, ISODateTime


class ProviderArtist(BaseModel):
    """Artist metadata normalised across providers."""

    model_config = ConfigDict(frozen=True)

    id: Optional[ID] = None
    name: str
    uri: Optional[URI] = None
    genres: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

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

    id: Optional[ID] = None
    name: str
    uri: Optional[URI] = None
    artists: List[ProviderArtist] = Field(default_factory=list)
    release_date: Optional[ISODateTime] = None
    total_tracks: Optional[int] = Field(default=None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

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

    id: Optional[ID] = None
    name: str
    provider: str
    uri: Optional[URI] = None
    artists: List[ProviderArtist] = Field(default_factory=list)
    album: Optional[ProviderAlbum] = None
    duration_ms: Optional[int] = Field(default=None, ge=0)
    isrc: Optional[str] = None
    score: Optional[float] = Field(default=None, ge=0.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "provider")
    @classmethod
    def _ensure_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped


__all__ = ["ProviderAlbum", "ProviderArtist", "ProviderTrack"]
