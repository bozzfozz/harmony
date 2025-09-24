"""Spotify client wrapper used by Harmony."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from app.config import SpotifyConfig
from app.logging import get_logger

try:  # pragma: no cover - import guard
    import spotipy
    from spotipy import Spotify
    from spotipy.oauth2 import SpotifyOAuth
    from spotipy.exceptions import SpotifyException
except Exception:  # pragma: no cover - during tests we mock the client
    spotipy = None
    Spotify = Any  # type: ignore
    SpotifyOAuth = Any  # type: ignore

    class SpotifyException(Exception):  # type: ignore
        http_status: Optional[int] = None


logger = get_logger(__name__)


class SpotifyClient:
    """High level client around Spotipy with rate limiting and retries."""

    def __init__(
        self,
        config: SpotifyConfig,
        client: Optional[Spotify] = None,
        rate_limit_seconds: float = 0.2,
        max_retries: int = 3,
    ) -> None:
        self._config = config
        self._rate_limit_seconds = rate_limit_seconds
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._last_request_time = 0.0

        if client is not None:
            self._client = client
        else:
            if spotipy is None:
                raise RuntimeError("spotipy is required for SpotifyClient but is not installed")
            if not (config.client_id and config.client_secret and config.redirect_uri):
                raise ValueError("Spotify configuration is incomplete")

            auth_manager = SpotifyOAuth(
                client_id=config.client_id,
                client_secret=config.client_secret,
                redirect_uri=config.redirect_uri,
                scope=config.scope,
            )
            self._client = spotipy.Spotify(auth_manager=auth_manager)

    def _respect_rate_limit(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._rate_limit_seconds:
                time.sleep(self._rate_limit_seconds - elapsed)
            self._last_request_time = time.monotonic()

    def _execute(self, func, *args, **kwargs):
        backoff = 0.5
        for attempt in range(1, self._max_retries + 1):
            self._respect_rate_limit()
            try:
                return func(*args, **kwargs)
            except SpotifyException as exc:  # pragma: no cover - network errors are mocked in tests
                status = getattr(exc, "http_status", None)
                if status not in {429, 502, 503} or attempt == self._max_retries:
                    logger.error("Spotify API request failed", exc_info=exc)
                    raise
                logger.warning("Retrying Spotify API request due to status %s", status)
                time.sleep(backoff)
                backoff *= 2
            except Exception as exc:  # pragma: no cover
                if attempt == self._max_retries:
                    raise
                logger.warning("Retrying Spotify API request due to %s", exc)
                time.sleep(backoff)
                backoff *= 2

    def is_authenticated(self) -> bool:
        try:
            profile = self._execute(self._client.current_user)
        except Exception:
            return False
        return bool(profile)

    def search_tracks(self, query: str, limit: int = 20) -> Dict[str, Any]:
        return self._execute(self._client.search, q=query, type="track", limit=limit)

    def search_artists(self, query: str, limit: int = 20) -> Dict[str, Any]:
        return self._execute(self._client.search, q=query, type="artist", limit=limit)

    def search_albums(self, query: str, limit: int = 20) -> Dict[str, Any]:
        return self._execute(self._client.search, q=query, type="album", limit=limit)

    def get_user_playlists(self, limit: int = 50) -> Dict[str, Any]:
        return self._execute(self._client.current_user_playlists, limit=limit)

    def get_track_details(self, track_id: str) -> Dict[str, Any]:
        return self._execute(self._client.track, track_id)

    def get_audio_features(self, track_id: str) -> Dict[str, Any]:
        features = self._execute(self._client.audio_features, [track_id]) or []
        return features[0] if features else {}

    def get_multiple_audio_features(self, track_ids: List[str]) -> Dict[str, Any]:
        features = self._execute(self._client.audio_features, track_ids)
        return {"audio_features": features or []}

    def get_playlist_items(self, playlist_id: str, limit: int = 100) -> Dict[str, Any]:
        return self._execute(self._client.playlist_items, playlist_id, limit=limit)

    def add_tracks_to_playlist(self, playlist_id: str, track_uris: List[str]) -> Dict[str, Any]:
        return self._execute(self._client.playlist_add_items, playlist_id, track_uris)

    def remove_tracks_from_playlist(self, playlist_id: str, track_uris: List[str]) -> Dict[str, Any]:
        return self._execute(
            self._client.playlist_remove_all_occurrences_of_items, playlist_id, track_uris
        )

    def reorder_playlist_items(
        self, playlist_id: str, range_start: int, insert_before: int
    ) -> Dict[str, Any]:
        return self._execute(
            self._client.playlist_reorder_items,
            playlist_id,
            range_start=range_start,
            insert_before=insert_before,
        )

    def get_saved_tracks(self, limit: int = 20) -> Dict[str, Any]:
        return self._execute(self._client.current_user_saved_tracks, limit=limit)

    def save_tracks(self, track_ids: List[str]) -> Dict[str, Any]:
        return self._execute(self._client.current_user_saved_tracks_add, track_ids)

    def remove_saved_tracks(self, track_ids: List[str]) -> Dict[str, Any]:
        return self._execute(self._client.current_user_saved_tracks_delete, track_ids)

    def get_current_user(self) -> Dict[str, Any]:
        return self._execute(self._client.current_user)

    def get_top_tracks(self, limit: int = 20) -> Dict[str, Any]:
        return self._execute(self._client.current_user_top_tracks, limit=limit)

    def get_top_artists(self, limit: int = 20) -> Dict[str, Any]:
        return self._execute(self._client.current_user_top_artists, limit=limit)

    def get_recommendations(
        self,
        seed_tracks: Optional[List[str]] = None,
        seed_artists: Optional[List[str]] = None,
        seed_genres: Optional[List[str]] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": limit}
        if seed_tracks:
            params["seed_tracks"] = seed_tracks
        if seed_artists:
            params["seed_artists"] = seed_artists
        if seed_genres:
            params["seed_genres"] = seed_genres
        return self._execute(self._client.recommendations, **params)

    def get_followed_artists(self, limit: int = 50) -> Dict[str, Any]:
        return self._execute(self._client.current_user_followed_artists, limit=limit)

    def get_artist_releases(self, artist_id: str) -> Dict[str, Any]:
        return self._execute(
            self._client.artist_albums,
            artist_id,
            album_type="album,single,compilation",
        )
