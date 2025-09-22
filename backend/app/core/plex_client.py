"""Plex client wrapper used by the backend services."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from app.config.settings import config_manager
from app.utils.logging_config import get_logger

try:  # pragma: no cover - import guarded for environments without plexapi
    from plexapi.server import PlexServer  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - handled gracefully at runtime
    PlexServer = None  # type: ignore[assignment]


logger = get_logger("plex_client")


class PlexClient:
    """Small wrapper around :class:`plexapi.server.PlexServer`."""

    def __init__(self, base_url: str | None = None, token: str | None = None, library: str | None = None) -> None:
        config = config_manager.get_plex_config()

        self._base_url = base_url or config.get("base_url") or os.getenv("PLEX_URL")
        self._token = token or config.get("token")
        self._library_name = library or config.get("library") or "Music"
        self._client = None
        self._connect()

    def _connect(self) -> None:
        if PlexServer is None:
            logger.warning("plexapi not available - Plex client disabled")
            self._client = None
            return

        if not self._base_url or not self._token:
            logger.error("Missing Plex configuration: base_url=%s token_present=%s", self._base_url, bool(self._token))
            self._client = None
            return

        try:
            self._client = PlexServer(self._base_url, self._token)
            logger.info("Connected to Plex server at %s", self._base_url)
        except Exception as exc:  # pragma: no cover - defensive safety net
            logger.error("Failed to connect to Plex server: %s", exc)
            self._client = None

    def _get_music_library(self):
        if self._client is None:
            raise RuntimeError("Plex client is not connected")

        try:
            library = self._client.library.section(self._library_name)
        except Exception as exc:
            logger.error("Unable to access Plex library %s: %s", self._library_name, exc)
            raise RuntimeError("Failed to access Plex library") from exc
        return library

    def is_connected(self) -> bool:
        """Return ``True`` when a Plex server connection is established."""

        return self._client is not None

    def get_all_artists(self) -> List[Dict[str, Any]]:
        """Return a list of artists from the Plex music library."""

        library = self._get_music_library()
        try:
            artists = library.search(libtype="artist")
        except Exception as exc:
            logger.error("Failed to fetch Plex artists: %s", exc)
            raise RuntimeError("Failed to fetch Plex artists") from exc

        results: List[Dict[str, Any]] = []
        for artist in artists:
            artist_id = getattr(artist, "ratingKey", getattr(artist, "key", None))
            results.append({
                "id": str(artist_id) if artist_id is not None else None,
                "name": getattr(artist, "title", ""),
            })
        logger.info("Fetched %s Plex artists", len(results))
        return results

    def get_albums_by_artist(self, artist_id: str) -> List[Dict[str, Any]]:
        """Return all albums for a given Plex artist identifier."""

        library = self._get_music_library()
        try:
            artist = library.fetchItem(artist_id)
        except Exception as exc:
            logger.error("Failed to fetch Plex artist %s: %s", artist_id, exc)
            raise RuntimeError("Failed to fetch artist") from exc

        if artist is None:
            raise RuntimeError("Artist not found")

        try:
            albums = artist.albums()
        except Exception as exc:
            logger.error("Failed to load albums for Plex artist %s: %s", artist_id, exc)
            raise RuntimeError("Failed to fetch albums") from exc

        results: List[Dict[str, Any]] = []
        for album in albums:
            album_id = getattr(album, "ratingKey", getattr(album, "key", None))
            results.append({
                "id": str(album_id) if album_id is not None else None,
                "title": getattr(album, "title", ""),
                "artist_id": artist_id,
            })
        logger.info("Fetched %s albums for Plex artist %s", len(results), artist_id)
        return results

    def get_tracks_by_album(self, album_id: str) -> List[Dict[str, Any]]:
        """Return the tracks belonging to a Plex album identifier."""

        library = self._get_music_library()
        try:
            album = library.fetchItem(album_id)
        except Exception as exc:
            logger.error("Failed to fetch Plex album %s: %s", album_id, exc)
            raise RuntimeError("Failed to fetch album") from exc

        if album is None:
            raise RuntimeError("Album not found")

        try:
            tracks = album.tracks()
        except Exception as exc:
            logger.error("Failed to load tracks for Plex album %s: %s", album_id, exc)
            raise RuntimeError("Failed to fetch tracks") from exc

        results: List[Dict[str, Any]] = []
        for track in tracks:
            track_id = getattr(track, "ratingKey", getattr(track, "key", None))
            duration = getattr(track, "duration", None)
            if isinstance(duration, (int, float)):
                duration_value = int(duration)
            else:
                duration_value = None
            results.append({
                "id": str(track_id) if track_id is not None else None,
                "title": getattr(track, "title", ""),
                "album_id": album_id,
                "duration": duration_value,
            })
        logger.info("Fetched %s tracks for Plex album %s", len(results), album_id)
        return results
