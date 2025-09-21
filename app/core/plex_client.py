from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class PlexTrackInfo:
    title: str
    artist: str
    album: str
    rating_key: str


class PlexClient:
    """Simplified Plex client using in-memory data."""

    def __init__(self) -> None:
        self._tracks: List[PlexTrackInfo] = [
            PlexTrackInfo(title="Song One", artist="Artist A", album="Album X", rating_key="t1"),
            PlexTrackInfo(title="Song Two", artist="Artist B", album="Album Y", rating_key="t2"),
            PlexTrackInfo(title="Unrelated", artist="Different", album="Other", rating_key="t3"),
        ]

    def get_all_artists(self) -> List[str]:
        return sorted({track.artist for track in self._tracks})

    def search_tracks(self, query: str) -> List[PlexTrackInfo]:
        normalized = query.lower()
        return [track for track in self._tracks if normalized in track.title.lower()]
