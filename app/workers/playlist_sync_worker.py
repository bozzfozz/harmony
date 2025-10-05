"""Background worker that synchronises Spotify playlists into the database."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Iterable

from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Playlist
from app.utils.activity import record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat
from app.services.cache import ResponseCache

logger = get_logger(__name__)


class PlaylistSyncWorker:
    """Periodically fetches playlists for the authenticated user."""

    def __init__(
        self,
        spotify_client: SpotifyClient,
        interval_seconds: float = 900.0,
        *,
        response_cache: ResponseCache | None = None,
        api_base_path: str = "",
    ) -> None:
        self._client = spotify_client
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._response_cache = response_cache
        self._api_base_path = (api_base_path or "").strip()
        self._cache_prefixes: tuple[str, ...] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            record_worker_started("playlist")
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        was_running = self._running
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:  # pragma: no cover - cancellation lifecycle
                pass
            self._task = None
        mark_worker_status("playlist", WORKER_STOPPED)
        if was_running or self._task is not None:
            record_worker_stopped("playlist")

    async def _run(self) -> None:
        logger.info("PlaylistSyncWorker started")
        record_worker_heartbeat("playlist")
        try:
            while self._running:
                await self.sync_once()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:  # pragma: no cover - cancellation lifecycle
            logger.debug("PlaylistSyncWorker cancelled")
            raise
        finally:
            self._running = False
            logger.info("PlaylistSyncWorker stopped")

    async def sync_once(self) -> None:
        """Fetch playlists from Spotify and persist them."""

        try:
            response = await asyncio.to_thread(self._client.get_user_playlists)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to fetch playlists from Spotify: %s", exc)
            return

        items: list[dict[str, Any]] = []
        if isinstance(response, dict):
            raw_items = response.get("items")
            if isinstance(raw_items, Iterable):
                items = [item for item in raw_items if isinstance(item, dict)]
        elif isinstance(response, list):
            items = [item for item in response if isinstance(item, dict)]

        if not items:
            logger.debug("No playlists received from Spotify")
            return

        now = datetime.utcnow()

        try:
            processed = await asyncio.to_thread(self._persist_playlists, items, now)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to persist playlists: %s", exc)
            return

        if processed > 0:
            await self._invalidate_playlist_cache()

        logger.info("Synced %s playlists from Spotify", processed)
        record_worker_heartbeat("playlist")

    def _persist_playlists(self, items: list[dict[str, Any]], timestamp: datetime) -> int:
        processed = 0

        with session_scope() as session:
            for payload in items:
                playlist_id = payload.get("id")
                name = payload.get("name")
                if not playlist_id or not name:
                    continue

                track_count = self._extract_track_count(payload)
                playlist = session.get(Playlist, str(playlist_id))

                if playlist is None:
                    playlist = Playlist(
                        id=str(playlist_id),
                        name=str(name),
                        track_count=track_count,
                    )
                    playlist.updated_at = timestamp
                    session.add(playlist)
                else:
                    playlist.name = str(name)
                    playlist.track_count = track_count
                    playlist.updated_at = timestamp

                processed += 1

        return processed

    async def _invalidate_playlist_cache(self) -> None:
        if self._response_cache is None:
            return

        prefixes = self._resolve_cache_prefixes()
        if not prefixes:
            return

        for prefix in prefixes:
            try:
                await self._response_cache.invalidate_prefix(prefix)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "Failed to invalidate playlist cache prefix %s: %s", prefix, exc
                )

    def _resolve_cache_prefixes(self) -> tuple[str, ...]:
        if self._cache_prefixes is not None:
            return self._cache_prefixes

        playlist_path = "/spotify/playlists"
        prefixes: list[str] = []

        base_prefix = self._compose_path(playlist_path)
        if base_prefix:
            prefixes.append(f"GET:{base_prefix}")

        prefixes.append(f"GET:{playlist_path}")

        # Deduplicate while preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for prefix in prefixes:
            if prefix not in seen:
                ordered.append(prefix)
                seen.add(prefix)

        self._cache_prefixes = tuple(ordered)
        return self._cache_prefixes

    def _compose_path(self, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        base = self._api_base_path
        if not base or base == "/":
            return normalized_path
        base_prefix = base.rstrip("/")
        return f"{base_prefix}{normalized_path}"

    @staticmethod
    def _extract_track_count(payload: dict[str, Any]) -> int:
        """Safely derive the track count from a playlist payload."""

        track_count: int = 0
        tracks = payload.get("tracks")
        if isinstance(tracks, dict):
            total = tracks.get("total")
            try:
                track_count = int(total)
            except (TypeError, ValueError):
                track_count = 0
        elif isinstance(tracks, Iterable) and not isinstance(tracks, (str, bytes)):
            track_count = sum(1 for _ in tracks)
        else:
            try:
                track_count = int(payload.get("track_count", 0))
            except (TypeError, ValueError):
                track_count = 0

        return max(track_count, 0)
