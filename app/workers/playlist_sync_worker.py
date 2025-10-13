"""Background worker that synchronises Spotify playlists into the database."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.logging_events import log_event
from app.models import Playlist
from app.services.cache import (
    PLAYLIST_LIST_CACHE_PREFIX,
    ResponseCache,
    playlist_detail_cache_key,
)
from app.utils.activity import record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat

logger = get_logger(__name__)

_UPDATED_AT_INCREMENT = timedelta(microseconds=1)


class PlaylistCacheInvalidator:
    """Synchronous wrapper that invalidates cached playlist responses."""

    def __init__(
        self,
        cache: ResponseCache,
        *,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._cache = cache
        self._loop = loop
        self._reason = "playlist_updated"
        self._list_prefix = f"{PLAYLIST_LIST_CACHE_PREFIX}:"

    def invalidate(self, playlist_ids: Iterable[str]) -> None:
        ordered_ids: list[str] = []
        seen_ids: set[str] = set()
        for playlist_id in playlist_ids:
            if not isinstance(playlist_id, str):
                continue
            trimmed = playlist_id.strip()
            if not trimmed or trimmed in seen_ids:
                continue
            ordered_ids.append(trimmed)
            seen_ids.add(trimmed)

        future = asyncio.run_coroutine_threadsafe(
            self._invalidate_targets(tuple(ordered_ids)), self._loop
        )

        try:
            invalidated = future.result()
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Failed to invalidate playlist cache entries: %s", exc)
            log_event(
                logger,
                "worker.playlists.cache.invalidate",
                component="worker.playlist_sync",
                status="error",
                error=str(exc),
                meta={"playlist_ids": tuple(ordered_ids)} if ordered_ids else None,
            )
            return

        status = "ok" if invalidated else "noop"
        log_event(
            logger,
            "worker.playlists.cache.invalidate",
            component="worker.playlist_sync",
            status=status,
            invalidated_entries=int(invalidated),
            playlist_count=len(ordered_ids),
            reason=self._reason,
            meta={"playlist_ids": tuple(ordered_ids)} if ordered_ids else None,
        )
        if invalidated:
            logger.info(
                "Invalidated %s cached Spotify playlist responses",
                invalidated,
                extra={"playlist_ids": tuple(ordered_ids)},
            )

    async def _invalidate_targets(self, playlist_ids: tuple[str, ...]) -> int:
        total = 0
        total += await self._cache.invalidate_prefix(
            self._list_prefix,
            reason=self._reason,
            path="/spotify/playlists",
        )
        total += await self._cache.invalidate_path(
            "/spotify/playlists",
            reason=self._reason,
        )

        for playlist_id in playlist_ids:
            key_prefix = playlist_detail_cache_key(playlist_id)
            detail_path = f"/spotify/playlists/{playlist_id}/tracks"
            total += await self._cache.invalidate_prefix(
                key_prefix,
                reason=self._reason,
                entity_id=playlist_id,
                path=detail_path,
            )
            total += await self._cache.invalidate_path(
                detail_path,
                reason=self._reason,
                entity_id=playlist_id,
            )

        return total


class PlaylistSyncWorker:
    """Periodically fetches playlists for the authenticated user."""

    def __init__(
        self,
        spotify_client: SpotifyClient,
        interval_seconds: float = 900.0,
        *,
        response_cache: ResponseCache | None = None,
    ) -> None:
        self._client = spotify_client
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._response_cache = response_cache

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

        cache_invalidator = self._build_cache_invalidator()

        try:
            processed = await asyncio.to_thread(
                self._persist_playlists, items, now, cache_invalidator
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to persist playlists: %s", exc)
            return

        logger.info("Synced %s playlists from Spotify", processed)
        record_worker_heartbeat("playlist")

    def _persist_playlists(
        self,
        items: list[dict[str, Any]],
        timestamp: datetime,
        cache_invalidator: PlaylistCacheInvalidator | None,
    ) -> int:
        processed = 0
        updated_ids: list[str] = []
        seen_ids: set[str] = set()
        commit_successful = False
        last_assigned: datetime | None = None

        try:
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
                        playlist.updated_at = self._compute_next_updated_at(
                            previous=None,
                            candidate=timestamp,
                            floor=last_assigned,
                        )
                        session.add(playlist)
                    else:
                        playlist.name = str(name)
                        playlist.track_count = track_count
                        playlist.updated_at = self._compute_next_updated_at(
                            previous=playlist.updated_at,
                            candidate=timestamp,
                            floor=last_assigned,
                        )

                    last_assigned = playlist.updated_at
                    processed += 1
                    playlist_id_str = str(playlist_id)
                    if playlist_id_str not in seen_ids:
                        updated_ids.append(playlist_id_str)
                        seen_ids.add(playlist_id_str)

            commit_successful = True
        finally:
            if commit_successful and cache_invalidator is not None and updated_ids:
                cache_invalidator.invalidate(tuple(updated_ids))

        return processed

    @staticmethod
    def _compute_next_updated_at(
        *,
        previous: datetime | None,
        candidate: datetime,
        floor: datetime | None,
    ) -> datetime:
        """Ensure the assigned timestamp is strictly newer than prior values."""

        target = candidate

        if floor is not None and target <= floor:
            target = floor + _UPDATED_AT_INCREMENT

        if previous is not None and target <= previous:
            target = previous + _UPDATED_AT_INCREMENT

        if floor is not None and target <= floor:
            target = floor + _UPDATED_AT_INCREMENT

        return target

    def _build_cache_invalidator(self) -> PlaylistCacheInvalidator | None:
        if self._response_cache is None:
            return None

        if not getattr(self._response_cache, "write_through", True):
            return None

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - defensive guard
            logger.debug("No running event loop available for cache invalidation")
            return None

        return PlaylistCacheInvalidator(
            self._response_cache,
            loop=loop,
        )

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
        elif isinstance(tracks, Iterable) and not isinstance(tracks, str | bytes):
            track_count = sum(1 for _ in tracks)
        else:
            try:
                track_count = int(payload.get("track_count", 0))
            except (TypeError, ValueError):
                track_count = 0

        return max(track_count, 0)
