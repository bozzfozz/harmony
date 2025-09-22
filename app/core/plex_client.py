from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class PlexTrackInfo:
    title: str
    artist: str
    album: str
    rating_key: str
    duration: int | None = None
    year: int | None = None


@dataclass
class PlexAlbumInfo:
    title: str
    artist: str
    year: int | None
    track_count: int


class PlexClient:
    """Simplified Plex client using in-memory data."""

    def __init__(self) -> None:
        self._connected = True
        self._libraries: List[str] = ["Music"]
        self._refresh_count = 0
        self._tracks: List[PlexTrackInfo] = [
            PlexTrackInfo(
                title="Song One",
                artist="Artist A",
                album="Album X",
                rating_key="t1",
                duration=210,
                year=2020,
            ),
            PlexTrackInfo(
                title="Song Two",
                artist="Artist B",
                album="Album Y",
                rating_key="t2",
                duration=198,
                year=2019,
            ),
            PlexTrackInfo(
                title="Unrelated",
                artist="Different",
                album="Other",
                rating_key="t3",
                duration=250,
                year=None,
            ),
        ]

        album_map: Dict[Tuple[str, str], PlexAlbumInfo] = {}
        for track in self._tracks:
            key = (track.album, track.artist)
            album = album_map.get(key)
            if album is None:
                album_map[key] = PlexAlbumInfo(
                    title=track.album,
                    artist=track.artist,
                    year=track.year,
                    track_count=1,
                )
            else:
                album.track_count += 1
                if album.year is None and track.year is not None:
                    album.year = track.year
        self._albums: List[PlexAlbumInfo] = list(album_map.values())

    def is_connected(self) -> bool:
        return self._connected

    def list_libraries(self) -> List[str]:
        return list(self._libraries)

    def get_all_artists(self) -> List[str]:
        return sorted({track.artist for track in self._tracks})

    def search_tracks(self, query: str) -> List[PlexTrackInfo]:
        normalized = query.lower()
        return [
            track
            for track in self._tracks
            if normalized in track.title.lower() or normalized in track.artist.lower()
        ]

    def search_albums(self, query: str) -> List[PlexAlbumInfo]:
        normalized = query.lower()
        return [
            album
            for album in self._albums
            if normalized in album.title.lower() or normalized in album.artist.lower()
        ]

    def refresh_library(self) -> bool:
        """Simulate a Plex library refresh."""

        self._refresh_count += 1
        return True
