"""Soulseek (slskd) adapter implementing the :class:`MusicProvider` contract."""

from __future__ import annotations

from typing import Iterable

from app.core.soulseek_client import SoulseekClient
from app.integrations.base import Album, Artist, MusicProvider, Playlist, ProviderError, Track


def _default_artist(name: str) -> Artist:
    return Artist(id=name or "unknown", name=name or "Unknown Artist")


def _track_from_payload(payload: dict) -> Track:
    title = str(payload.get("title") or payload.get("name") or "")
    artist_name = str(payload.get("artist") or payload.get("username") or "")
    artist = _default_artist(artist_name or "Unknown Artist")
    album_name = payload.get("album")
    album = None
    if album_name:
        album = Album(
            id=f"slskd:{artist.id}:{album_name}",
            name=str(album_name),
            artists=(artist,),
            release_year=None,
            total_tracks=None,
        )
    duration = payload.get("duration")
    if isinstance(duration, str) and duration.isdigit():
        duration_ms = int(duration) * 1000
    else:
        duration_ms = None
    return Track(
        id=str(payload.get("id") or payload.get("objectKey") or title),
        name=title,
        artists=(artist,),
        album=album,
        duration_ms=duration_ms,
    )


class SlskdAdapter(MusicProvider):
    """Adapter mapping Soulseek search results to Harmony domain objects."""

    name = "slskd"

    def __init__(self, *, client: SoulseekClient, timeout_ms: int) -> None:
        self._client = client
        self._timeout_ms = timeout_ms

    def search_tracks(self, query: str, limit: int = 20) -> Iterable[Track]:
        raise ProviderError(self.name, "Synchronous search is not supported for slskd")

    def get_artist(self, artist_id: str) -> Artist:
        raise ProviderError(self.name, "Artist metadata is not available from slskd")

    def get_album(self, album_id: str) -> Album:
        raise ProviderError(self.name, "Album metadata is not available from slskd")

    def get_artist_top_tracks(self, artist_id: str, limit: int = 10) -> Iterable[Track]:
        raise ProviderError(self.name, "Top tracks are not available from slskd")

    def get_playlist(self, playlist_id: str) -> Playlist:
        raise ProviderError(self.name, "Playlists are not available from slskd")
