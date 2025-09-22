"""Plex client integration for Harmony."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import PlexConfig
from app.logging import get_logger

try:  # pragma: no cover - we mock Plex in tests
    from plexapi.server import PlexServer
except Exception:  # pragma: no cover
    PlexServer = None  # type: ignore


logger = get_logger(__name__)


class PlexClient:
    """Wrapper around :class:`plexapi.server.PlexServer`."""

    def __init__(self, config: PlexConfig, server: Optional[PlexServer] = None) -> None:
        self._config = config
        if server is not None:
            self._server = server
        else:
            if PlexServer is None:
                raise RuntimeError("plexapi is required for PlexClient but is not installed")
            if not (config.base_url and config.token):
                raise ValueError("Plex configuration is incomplete")
            self._server = PlexServer(config.base_url, config.token)

    def _get_music_section(self):  # pragma: no cover - exercised via mocks
        library = self._server.library
        if self._config.library_name:
            return library.section(self._config.library_name)
        for section in library.sections():
            if getattr(section, "type", None) == "artist":
                return section
        raise RuntimeError("No music library found in Plex server")

    def is_connected(self) -> bool:
        try:
            self._get_music_section()
        except Exception as exc:
            logger.error("Unable to connect to Plex", exc_info=exc)
            return False
        return True

    def get_all_artists(self) -> List[Dict[str, Any]]:
        section = self._get_music_section()
        artists = section.search(libtype="artist")
        return [
            {"id": str(artist.ratingKey), "name": artist.title}
            for artist in artists
        ]

    def get_albums_by_artist(self, artist_id: str) -> List[Dict[str, Any]]:
        section = self._get_music_section()
        artist = section.fetchItem(int(artist_id))
        albums = artist.albums()
        return [
            {"id": str(album.ratingKey), "title": album.title, "year": getattr(album, "year", None)}
            for album in albums
        ]

    def get_tracks_by_album(self, album_id: str) -> List[Dict[str, Any]]:
        section = self._get_music_section()
        album = section.fetchItem(int(album_id))
        tracks = album.tracks()
        return [
            {
                "id": str(track.ratingKey),
                "title": track.title,
                "duration": getattr(track, "duration", None),
                "index": getattr(track, "index", None),
            }
            for track in tracks
        ]
