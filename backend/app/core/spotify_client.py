"""Spotify client wrapper adding rate limiting and retry support."""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, Iterable, List

from app.config.settings import config_manager
from app.utils.logging_config import get_logger

try:  # pragma: no cover - handled gracefully during testing when spotipy is absent
    import spotipy
    from spotipy import Spotify
    from spotipy.exceptions import SpotifyException
    from spotipy.oauth2 import SpotifyOAuth
except ModuleNotFoundError:  # pragma: no cover - optional dependency for exercises
    spotipy = None  # type: ignore[assignment]
    Spotify = Any  # type: ignore[misc,assignment]
    SpotifyOAuth = Any  # type: ignore[misc,assignment]

    class SpotifyException(Exception):
        """Fallback exception used when spotipy is unavailable."""


logger = get_logger("spotify_client")


class SpotifyClient:
    """Wrapper around :mod:`spotipy` providing Harmony specific helpers."""

    RETRYABLE_STATUS = {429, 502, 503}

    def __init__(
        self,
        client: Spotify | None = None,
        auth_manager: SpotifyOAuth | None = None,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        scope: str | None = None,
        rate_limit_seconds: float = 0.2,
        max_retries: int = 3,
    ) -> None:
        config = config_manager.get_spotify_config()

        self._client_id = client_id or config.get("client_id") or os.getenv("SPOTIFY_CLIENT_ID")
        self._client_secret = (
            client_secret or config.get("client_secret") or os.getenv("SPOTIFY_CLIENT_SECRET")
        )
        self._redirect_uri = (
            redirect_uri or config.get("redirect_uri") or os.getenv("SPOTIFY_REDIRECT_URI")
        )
        self._scope = scope or config.get("scope") or "user-library-read playlist-read-private"

        self._rate_limit_seconds = max(rate_limit_seconds, 0.0)
        self._max_retries = max(max_retries, 1)
        self._last_call = 0.0

        if client is not None:
            self._client = client
            self._auth_manager = auth_manager
        elif spotipy is None:
            logger.warning("spotipy not installed - Spotify client disabled")
            self._client = None
            self._auth_manager = auth_manager
        else:
            if auth_manager is None:
                auth_manager = SpotifyOAuth(
                    client_id=self._client_id,
                    client_secret=self._client_secret,
                    redirect_uri=self._redirect_uri,
                    scope=self._scope,
                )
            self._auth_manager = auth_manager
            self._client = Spotify(auth_manager=self._auth_manager)

        logger.info("Spotify client initialised (scopes=%s)", self._scope)

    # ------------------------------------------------------------------
    # Helpers
    def _enforce_rate_limit(self) -> None:
        """Ensure at least ``rate_limit_seconds`` between Spotify API calls."""

        if self._rate_limit_seconds <= 0:
            return

        elapsed = time.monotonic() - self._last_call
        if elapsed < self._rate_limit_seconds:
            sleep_time = self._rate_limit_seconds - elapsed
            logger.debug("Sleeping %.3fs to respect Spotify rate limit", sleep_time)
            time.sleep(sleep_time)

    def _execute_with_retry(self, action: str, func: Callable[[], Any]) -> Any:
        """Execute ``func`` with retry handling for transient Spotify errors."""

        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            self._enforce_rate_limit()
            try:
                result = func()
            except SpotifyException as exc:  # pragma: no cover - exercised in unit tests via mocks
                status = getattr(exc, "http_status", None)
                headers: Dict[str, Any] = getattr(exc, "headers", {}) or {}
                retry_after = headers.get("Retry-After") or headers.get("retry-after")
                if status in self.RETRYABLE_STATUS and attempt < self._max_retries:
                    delay = self._calculate_retry_delay(status, retry_after, attempt)
                    logger.warning(
                        "Spotify call %s failed with status %s (attempt %s/%s) - retrying in %.2fs",
                        action,
                        status,
                        attempt,
                        self._max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    last_exc = exc
                    continue
                logger.error("Spotify call %s failed: %s", action, exc)
                raise
            except Exception as exc:  # pragma: no cover - defensive safety net
                logger.error("Spotify call %s raised unexpected error: %s", action, exc)
                last_exc = exc
            else:
                self._last_call = time.monotonic()
                return result

            self._last_call = time.monotonic()

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Spotify call {action} failed")

    def _calculate_retry_delay(self, status: int | None, retry_after: Any, attempt: int) -> float:
        if status == 429 and retry_after is not None:
            try:
                return max(float(retry_after), self._rate_limit_seconds)
            except (TypeError, ValueError):
                logger.debug("Retry-After header invalid: %s", retry_after)
        # Exponential backoff for other cases
        return min(2.0 ** attempt * 0.5, 10.0)

    def _ensure_client(self) -> Spotify:
        if self._client is None:
            raise RuntimeError("Spotify client not available")
        return self._client

    # ------------------------------------------------------------------
    # Public API
    def is_authenticated(self) -> bool:
        """Return ``True`` if the OAuth manager currently holds a token."""

        auth_manager = getattr(self, "_auth_manager", None)
        if auth_manager is None:
            return self._client is not None

        token_info: Dict[str, Any] | None = None
        try:
            get_token = getattr(auth_manager, "get_cached_token", None)
            if callable(get_token):
                token_info = get_token()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to read cached Spotify token: %s", exc)
            return False

        return bool(token_info and token_info.get("access_token"))

    def search_tracks(self, query: str, limit: int = 20) -> List[dict[str, Any]]:
        """Search Spotify tracks matching ``query``."""

        logger.info("Searching Spotify tracks for query=%s limit=%s", query, limit)
        client = self._ensure_client()

        def _call() -> Any:
            return client.search(q=query, type="track", limit=limit)

        data = self._execute_with_retry("search_tracks", _call)
        tracks = data.get("tracks", {}).get("items", []) if isinstance(data, dict) else []
        return [self._format_track(item) for item in tracks]

    def search_artists(self, query: str, limit: int = 20) -> List[dict[str, Any]]:
        """Search Spotify artists for ``query``."""

        logger.info("Searching Spotify artists for query=%s limit=%s", query, limit)
        client = self._ensure_client()

        def _call() -> Any:
            return client.search(q=query, type="artist", limit=limit)

        data = self._execute_with_retry("search_artists", _call)
        artists = data.get("artists", {}).get("items", []) if isinstance(data, dict) else []
        return [self._format_artist(item) for item in artists]

    def search_albums(self, query: str, limit: int = 20) -> List[dict[str, Any]]:
        """Search Spotify albums for ``query``."""

        logger.info("Searching Spotify albums for query=%s limit=%s", query, limit)
        client = self._ensure_client()

        def _call() -> Any:
            return client.search(q=query, type="album", limit=limit)

        data = self._execute_with_retry("search_albums", _call)
        albums = data.get("albums", {}).get("items", []) if isinstance(data, dict) else []
        return [self._format_album(item) for item in albums]

    def get_user_playlists(self) -> List[dict[str, Any]]:
        """Return playlists of the current Spotify user."""

        logger.info("Fetching current user playlists")
        client = self._ensure_client()

        def _call() -> Any:
            return client.current_user_playlists()

        data = self._execute_with_retry("get_user_playlists", _call)
        playlists = data.get("items", []) if isinstance(data, dict) else []
        return [self._format_playlist(item) for item in playlists]

    def get_track_details(self, track_id: str) -> dict[str, Any]:
        """Return detailed information for a Spotify track."""

        logger.info("Fetching Spotify track details for %s", track_id)
        client = self._ensure_client()

        def _call() -> Any:
            return client.track(track_id)

        data = self._execute_with_retry("get_track_details", _call)
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected response from Spotify track API")
        return self._format_track_details(data)

    # ------------------------------------------------------------------
    # Formatting helpers
    def _format_track(self, item: Dict[str, Any]) -> Dict[str, Any]:
        artists = self._extract_names(item.get("artists", []))
        album = item.get("album", {})
        album_name = album.get("name") if isinstance(album, dict) else None
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "artists": artists,
            "album": album_name,
            "duration_ms": item.get("duration_ms"),
            "popularity": item.get("popularity"),
        }

    def _format_artist(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "genres": list(item.get("genres", []) or []),
            "followers": item.get("followers", {}).get("total") if isinstance(item.get("followers"), dict) else None,
        }

    def _format_album(self, item: Dict[str, Any]) -> Dict[str, Any]:
        artists = self._extract_names(item.get("artists", []))
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "artists": artists,
            "release_date": item.get("release_date"),
            "total_tracks": item.get("total_tracks"),
        }

    def _format_playlist(self, item: Dict[str, Any]) -> Dict[str, Any]:
        owner = item.get("owner", {})
        owner_name = owner.get("display_name") if isinstance(owner, dict) else None
        tracks = item.get("tracks", {})
        track_count = tracks.get("total") if isinstance(tracks, dict) else None
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "owner": owner_name,
            "tracks": track_count,
        }

    def _format_track_details(self, item: Dict[str, Any]) -> Dict[str, Any]:
        album = item.get("album", {}) if isinstance(item.get("album"), dict) else {}
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "artists": self._extract_names(item.get("artists", [])),
            "album": {
                "id": album.get("id"),
                "name": album.get("name"),
                "release_date": album.get("release_date"),
            },
            "duration_ms": item.get("duration_ms"),
            "popularity": item.get("popularity"),
            "preview_url": item.get("preview_url"),
            "uri": item.get("uri"),
        }

    def _extract_names(self, items: Iterable[Any]) -> List[str]:
        names: List[str] = []
        for value in items:
            if isinstance(value, dict):
                name = value.get("name")
            else:
                name = value
            if isinstance(name, str) and name:
                names.append(name)
        return names


__all__ = ["SpotifyClient"]

