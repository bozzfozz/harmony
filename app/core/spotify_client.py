from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


@dataclass
class Artist:
    id: str
    name: str


@dataclass
class Album:
    id: str
    title: str
    artist: str
    year: Optional[int] = None

    @classmethod
    def from_spotify_album(cls, data: dict) -> "Album":
        album_info = data.get("album", {})
        album_name = album_info.get("name") if isinstance(album_info, dict) else data.get("name", "")
        artists = data.get("artists", [])
        if artists and isinstance(artists[0], dict):
            artist_name = artists[0].get("name", "")
        elif artists:
            artist_name = artists[0]
        else:
            artist_name = data.get("artist", "")

        return cls(
            id=data.get("id", ""),
            title=album_name,
            artist=artist_name,
            year=data.get("release_year"),
        )


@dataclass
class Track:
    id: str
    title: str
    artist: str
    album: str
    duration_ms: int
    album_id: Optional[str] = None

    @classmethod
    def from_spotify_track(cls, data: dict) -> "Track":
        album_data = data.get("album") or data.get("album_name", "")
        if isinstance(album_data, dict):
            album_name = album_data.get("name", "")
            album_id = album_data.get("id")
        else:
            album_name = album_data or ""
            album_id = None

        artists = data.get("artists")
        if isinstance(artists, list):
            if artists and isinstance(artists[0], dict):
                artist_name = artists[0].get("name", "")
            elif artists:
                artist_name = artists[0]
            else:
                artist_name = ""
        elif isinstance(artists, dict):
            artist_name = artists.get("name", "")
        else:
            artist_name = data.get("artist", "")

        return cls(
            id=data.get("id", ""),
            title=data.get("title") or data.get("name", ""),
            artist=artist_name,
            album=album_name,
            duration_ms=int(data.get("duration_ms", 0)),
            album_id=album_id,
        )


@dataclass
class Playlist:
    id: str
    name: str
    track_count: int


class SpotifyClient:
    """Simple in-memory Spotify client used for prototyping."""

    def __init__(self) -> None:
        self._authenticated = True
        self._albums: List[dict] = [
            {
                "id": "alb1",
                "name": "Album X",
                "artists": [{"id": "artist-a", "name": "Artist A"}],
                "release_year": 2020,
            },
            {
                "id": "alb2",
                "name": "Album Y",
                "artists": [{"id": "artist-b", "name": "Artist B"}],
                "release_year": 2019,
            },
        ]
        self._album_index = {album["id"]: album for album in self._albums}
        self._tracks: List[Track] = [
            Track(
                id="1",
                title="Song One",
                artist="Artist A",
                album="Album X",
                duration_ms=210_000,
                album_id="alb1",
            ),
            Track(
                id="2",
                title="Song Two",
                artist="Artist B",
                album="Album Y",
                duration_ms=180_000,
                album_id="alb2",
            ),
            Track(
                id="3",
                title="Another Song",
                artist="Artist A",
                album="Album X",
                duration_ms=200_000,
                album_id="alb1",
            ),
        ]
        self._track_index = {track.id: track for track in self._tracks}
        self._playlists: List[Playlist] = [
            Playlist(id="p1", name="Favorites", track_count=15),
            Playlist(id="p2", name="Chill", track_count=24),
        ]
        self._playlist_tracks: Dict[str, List[str]] = {
            "p1": ["1", "2"],
            "p2": ["3"],
        }

    def is_authenticated(self) -> bool:
        return self._authenticated

    def get_user_playlists_metadata_only(self) -> List[Playlist]:
        return list(self._playlists)

    def get_track(self, track_id: str) -> Optional[Track]:
        """Return a track by id if present."""

        track = self._track_index.get(track_id)
        if track is None:
            return None
        return Track(
            id=track.id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_ms=track.duration_ms,
            album_id=track.album_id,
        )

    def search_tracks(self, query: str) -> List[Track]:
        normalized = query.lower()
        return [track for track in self._tracks if normalized in track.title.lower()]

    def get_artist_discography(self, artist_name: str) -> Iterable[Album]:
        normalized = artist_name.lower()
        albums = {track.album for track in self._tracks if track.artist.lower() == normalized}
        return [Album(id=f"album-{i}", title=title, artist=artist_name) for i, title in enumerate(albums)]

    def get_track_details(self, track_id: str) -> Optional[dict]:
        track = self._track_index.get(track_id)
        if track is None:
            return None

        album_data = self._album_index.get(track.album_id, {})
        raw_data = {
            "id": track.id,
            "name": track.title,
            "artists": [{"name": track.artist}],
            "album": {
                "id": album_data.get("id"),
                "name": album_data.get("name", track.album),
            },
            "duration_ms": track.duration_ms,
        }

        return {
            "id": track.id,
            "name": track.title,
            "artists": [track.artist],
            "album": track.album,
            "duration_ms": track.duration_ms,
            "raw_data": raw_data,
        }

    def get_album(self, album_id: str) -> Optional[dict]:
        album = self._album_index.get(album_id)
        if album is None:
            return None
        return album.copy()

    def get_playlist_tracks(self, playlist_id: str) -> List[Track]:
        """Return tracks for the playlist if available."""

        track_ids = self._playlist_tracks.get(playlist_id, [])
        return [
            Track(
                id=self._track_index[track_id].id,
                title=self._track_index[track_id].title,
                artist=self._track_index[track_id].artist,
                album=self._track_index[track_id].album,
                duration_ms=self._track_index[track_id].duration_ms,
                album_id=self._track_index[track_id].album_id,
            )
            for track_id in track_ids
            if track_id in self._track_index
        ]
