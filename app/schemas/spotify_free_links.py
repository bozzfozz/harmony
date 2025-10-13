"""Pydantic models for the Spotify FREE links endpoint."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, Field


class FreeLinksRequest(BaseModel):
    """Input payload accepting a single URL or multiple URLs."""

    url: str | None = Field(default=None, description="Single Spotify playlist link")
    urls: Sequence[str] | None = Field(
        default=None, description="Collection of Spotify playlist links"
    )

    def _collect_urls(self) -> list[str]:
        values: list[str] = []
        if self.url is not None:
            values.append(self.url)
        if self.urls is not None:
            values.extend(self.urls)
        return values

    def iter_urls(self) -> Iterable[str]:
        return list(self._collect_urls())


class AcceptedPlaylist(BaseModel):
    playlist_id: str = Field(..., description="Normalized Spotify playlist identifier")
    url: str = Field(..., description="Canonical Spotify playlist URL")


class SkippedPlaylist(BaseModel):
    url: str = Field(..., description="Original URL submitted by the user")
    reason: Literal["duplicate", "invalid", "non_playlist"] = Field(...)


class FreeLinksResponse(BaseModel):
    accepted: list[AcceptedPlaylist] = Field(default_factory=list)
    skipped: list[SkippedPlaylist] = Field(default_factory=list)
