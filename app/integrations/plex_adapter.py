"""Placeholder Plex adapter implementing :class:`MusicProvider`."""

from __future__ import annotations

from typing import Iterable

from app.integrations.base import Album, Artist, MusicProvider, Playlist, ProviderError, Track


class PlexAdapter(MusicProvider):
    """Stub adapter returning dependency errors until Plex support is restored."""

    name = "plex"

    def __init__(self, *, timeout_ms: int) -> None:
        self._timeout_ms = timeout_ms

    def _disabled(self) -> ProviderError:
        return ProviderError(self.name, "Plex adapter is currently disabled")

    def search_tracks(self, query: str, limit: int = 20) -> Iterable[Track]:
        raise self._disabled()

    def get_artist(self, artist_id: str) -> Artist:
        raise self._disabled()

    def get_album(self, album_id: str) -> Album:
        raise self._disabled()

    def get_artist_top_tracks(self, artist_id: str, limit: int = 10) -> Iterable[Track]:
        raise self._disabled()

    def get_playlist(self, playlist_id: str) -> Playlist:
        raise self._disabled()
