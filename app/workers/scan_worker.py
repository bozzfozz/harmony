"""Worker that periodically scans the Plex library."""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select

from app.core.plex_client import PlexClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Setting

logger = get_logger(__name__)


class ScanWorker:
    def __init__(self, plex_client: PlexClient, interval_seconds: int = 600) -> None:
        self._client = plex_client
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = asyncio.Event()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._running.set()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running.clear()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:  # pragma: no cover
                pass

    async def _run(self) -> None:
        logger.info("ScanWorker started")
        while self._running.is_set():
            await self._perform_scan()
            await asyncio.sleep(self._interval)
        logger.info("ScanWorker stopped")

    async def _perform_scan(self) -> None:
        try:
            artists = self._client.get_all_artists()
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to scan Plex library: %s", exc)
            return

        artist_count = len(artists)
        album_count = 0
        track_count = 0

        for artist in artists:
            artist_id = artist.get("id")
            if not artist_id:
                continue
            try:
                albums = self._client.get_albums_by_artist(str(artist_id))
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to fetch albums for Plex artist %s: %s", artist_id, exc
                )
                continue
            album_count += len(albums)

            for album in albums:
                album_id = album.get("id")
                if not album_id:
                    continue
                try:
                    tracks = self._client.get_tracks_by_album(str(album_id))
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning(
                        "Failed to fetch tracks for Plex album %s: %s", album_id, exc
                    )
                    continue
                track_count += len(tracks)

        now = datetime.utcnow()
        with session_scope() as session:
            self._upsert_setting(session, "plex_artist_count", str(artist_count), now)
            self._upsert_setting(session, "plex_album_count", str(album_count), now)
            self._upsert_setting(session, "plex_track_count", str(track_count), now)
            self._upsert_setting(
                session, "plex_last_scan", now.isoformat(timespec="seconds"), now
            )
        logger.info(
            "Plex scan complete: %d artists, %d albums, %d tracks",
            artist_count,
            album_count,
            track_count,
        )

    @staticmethod
    def _upsert_setting(session, key: str, value: str, timestamp: datetime) -> None:
        setting = session.execute(
            select(Setting).where(Setting.key == key)
        ).scalar_one_or_none()
        if setting is None:
            session.add(
                Setting(
                    key=key,
                    value=value,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        else:
            setting.value = value
            setting.updated_at = timestamp
