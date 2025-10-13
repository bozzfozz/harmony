"""Base interfaces and domain models for music providers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True, frozen=True)
class Artist:
    """Normalized representation of an artist returned by a provider."""

    id: str
    name: str
    genres: tuple[str, ...] = ()
    popularity: int | None = None


@dataclass(slots=True, frozen=True)
class Album:
    """Normalized representation of an album returned by a provider."""

    id: str
    name: str
    artists: tuple[Artist, ...]
    release_year: int | None = None
    total_tracks: int | None = None


@dataclass(slots=True, frozen=True)
class Track:
    """Normalized representation of a track returned by a provider."""

    id: str
    name: str
    artists: tuple[Artist, ...]
    album: Album | None
    duration_ms: int | None
    isrc: str | None = None


@dataclass(slots=True, frozen=True)
class Playlist:
    """Normalized representation of a playlist returned by a provider."""

    id: str
    name: str
    owner: str | None
    description: str | None
    tracks: tuple[Track, ...]


@dataclass(slots=True, frozen=True)
class TrackCandidate:
    """Representation of a downloadable track candidate returned by a provider."""

    title: str
    artist: str | None
    format: str | None
    bitrate_kbps: int | None
    size_bytes: int | None
    seeders: int | None
    username: str | None
    availability: float | None
    source: str
    download_uri: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class MusicProvider(Protocol):
    """Interface implemented by all music provider adapters."""

    name: str

    def search_tracks(self, query: str, limit: int = 20) -> Iterable[Track]:
        """Return tracks for the search query."""

    def get_artist(self, artist_id: str) -> Artist:
        """Return the artist identified by ``artist_id``."""

    def get_album(self, album_id: str) -> Album:
        """Return the album identified by ``album_id``."""

    def get_artist_top_tracks(self, artist_id: str, limit: int = 10) -> Iterable[Track]:
        """Return the top tracks for the given artist."""

    def get_playlist(self, playlist_id: str) -> Playlist:
        """Return a playlist and its tracks."""


class MusicProviderAdapter(Protocol):
    """Specialised provider interface used by the integration service."""

    name: str

    async def search_tracks(
        self, query: str, artist: str | None = None, limit: int = 50
    ) -> list[TrackCandidate]:
        """Return a concrete list of download candidates for the supplied search query."""


class ProviderError(RuntimeError):
    """Raised when a provider interaction fails."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(message)
        self.provider = provider
        self.message = message
