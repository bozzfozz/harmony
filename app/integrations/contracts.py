"""Contracts shared by integration providers and the gateway."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.integrations.base import TrackCandidate


@dataclass(slots=True, frozen=True)
class SearchQuery:
    """Normalised search query sent to downstream providers."""

    text: str
    artist: str | None
    limit: int


@dataclass(slots=True, frozen=True)
class ProviderArtist:
    """Artist metadata returned by a provider."""

    source: str
    name: str
    source_id: str | None = None
    popularity: int | None = None
    genres: tuple[str, ...] = ()
    images: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def id(self) -> str | None:  # pragma: no cover - compatibility alias
        return self.source_id


@dataclass(slots=True, frozen=True)
class ProviderAlbum:
    """Album metadata returned by a provider search."""

    name: str
    id: str | None = None
    artists: tuple[ProviderArtist, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    release_date: str | None = None
    total_tracks: int | None = None
    images: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ProviderAlbumDetails:
    """Detailed album metadata including the canonical track listing."""

    source: str
    album: ProviderAlbum
    tracks: tuple[ProviderTrack, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ProviderTrack:
    """Track metadata enriched with downloadable candidates."""

    name: str
    provider: str
    id: str | None = None
    artists: tuple[ProviderArtist, ...] = ()
    album: ProviderAlbum | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    score: float | None = None
    candidates: tuple[TrackCandidate, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def source(self) -> str:
        """Compatibility alias for consumers expecting a ``source`` field."""

        return self.provider


class ProviderError(RuntimeError):
    """Base exception raised when a provider request fails."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: int | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.cause = cause


class ProviderTimeoutError(ProviderError):
    """Raised when the provider did not respond within the configured timeout."""

    def __init__(self, provider: str, timeout_ms: int, *, cause: Exception | None = None) -> None:
        super().__init__(provider, f"{provider} timed out after {timeout_ms}ms", cause=cause)
        self.timeout_ms = timeout_ms


class ProviderValidationError(ProviderError):
    """Raised when a provider rejects the request as invalid."""


class ProviderRateLimitedError(ProviderError):
    """Raised when a provider applied rate limits to the request."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        retry_after_ms: int | None = None,
        retry_after_header: str | None = None,
        cause: Exception | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            provider,
            message,
            status_code=status_code,
            cause=cause,
        )
        self.retry_after_ms = retry_after_ms
        self.retry_after_header = retry_after_header


class ProviderNotFoundError(ProviderError):
    """Raised when the provider reported that no resources matched the request."""


class ProviderDependencyError(ProviderError):
    """Raised when upstream dependencies failed while serving the request."""


class ProviderInternalError(ProviderError):
    """Raised when the provider returned an unexpected payload."""


@dataclass(slots=True, frozen=True)
class ProviderRelease:
    """Release metadata returned by a provider."""

    source: str
    source_id: str | None
    artist_source_id: str | None
    title: str
    release_date: str | None = None
    type: str | None = None
    total_tracks: int | None = None
    version: str | None = None
    updated_at: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


class TrackProvider(Protocol):
    """Protocol implemented by download-capable provider adapters."""

    name: str

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        """Return downloadable tracks for the supplied query."""

    async def fetch_artist(
        self, *, artist_id: str | None = None, name: str | None = None
    ) -> ProviderArtist | None:
        """Return artist metadata for the supplied identifier."""

    async def fetch_artist_releases(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderRelease]:
        """Return releases associated with the supplied artist."""

    async def fetch_album(self, album_source_id: str) -> ProviderAlbumDetails | None:
        """Return detailed album metadata for the supplied identifier."""

    async def fetch_artist_top_tracks(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderTrack]:
        """Return the provider's notion of an artist's top tracks."""


__all__ = [
    "ProviderAlbum",
    "ProviderAlbumDetails",
    "ProviderArtist",
    "ProviderDependencyError",
    "ProviderError",
    "ProviderInternalError",
    "ProviderNotFoundError",
    "ProviderRateLimitedError",
    "ProviderTimeoutError",
    "ProviderRelease",
    "ProviderTrack",
    "ProviderValidationError",
    "SearchQuery",
    "TrackProvider",
]
