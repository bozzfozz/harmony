from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class Artist:
    id: str
    name: str


@dataclass
class Album:
    id: str
    title: str
    artist: str


@dataclass
class Track:
    id: str
    title: str
    artist: str
    album: str
    duration_ms: int

    @classmethod
    def from_spotify_track(cls, data: dict) -> "Track":
        return cls(
            id=data.get("id", ""),
            title=data.get("title") or data.get("name", ""),
            artist=data.get("artist") or data.get("artists", [{}])[0].get("name", ""),
            album=data.get("album") or data.get("album_name", ""),
            duration_ms=int(data.get("duration_ms", 0)),
        )


@dataclass
class Playlist:
    id: str
    name: str
    track_count: int


class SpotifyClient:
    """Simple in-memory Spotify client used for prototyping."""

    def __init__(self) -> None:
        self._tracks: List[Track] = [
            Track(id="1", title="Song One", artist="Artist A", album="Album X", duration_ms=210_000),
            Track(id="2", title="Song Two", artist="Artist B", album="Album Y", duration_ms=180_000),
            Track(id="3", title="Another Song", artist="Artist A", album="Album Z", duration_ms=200_000),
        ]
        self._playlists: List[Playlist] = [
            Playlist(id="p1", name="Favorites", track_count=15),
            Playlist(id="p2", name="Chill", track_count=24),
        ]

    def get_user_playlists_metadata_only(self) -> List[Playlist]:
        return list(self._playlists)

    def search_tracks(self, query: str) -> List[Track]:
        normalized = query.lower()
        return [track for track in self._tracks if normalized in track.title.lower()]

    def get_artist_discography(self, artist_name: str) -> Iterable[Album]:
        normalized = artist_name.lower()
        albums = {track.album for track in self._tracks if track.artist.lower() == normalized}
        return [Album(id=f"album-{i}", title=title, artist=artist_name) for i, title in enumerate(albums)]
