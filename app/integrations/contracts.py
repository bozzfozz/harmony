"""Contracts shared by integration providers and the gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from app.integrations.base import TrackCandidate


@dataclass(slots=True, frozen=True)
class SearchQuery:
    """Normalised search query sent to downstream providers."""

    text: str
    artist: str | None
    limit: int


@dataclass(slots=True, frozen=True)
class ProviderArtist:
    """Artist metadata returned by a provider search."""

    name: str
    id: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ProviderAlbum:
    """Album metadata returned by a provider search."""

    name: str
    id: str | None = None
    artists: tuple[ProviderArtist, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ProviderTrack:
    """Track metadata enriched with downloadable candidates."""

    name: str
    provider: str
    artists: tuple[ProviderArtist, ...] = ()
    album: ProviderAlbum | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    candidates: tuple[TrackCandidate, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


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


class TrackProvider(Protocol):
    """Protocol implemented by download-capable provider adapters."""

    name: str

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        """Return downloadable tracks for the supplied query."""


__all__ = [
    "ProviderAlbum",
    "ProviderArtist",
    "ProviderDependencyError",
    "ProviderError",
    "ProviderInternalError",
    "ProviderNotFoundError",
    "ProviderRateLimitedError",
    "ProviderTimeoutError",
    "ProviderTrack",
    "ProviderValidationError",
    "SearchQuery",
    "TrackProvider",
]

