"""Worker that periodically scans the Plex library."""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.plex_client import PlexClient
from app.db import SessionLocal
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
        session: Session = SessionLocal()
        try:
            setting = session.execute(
                select(Setting).where(Setting.key == "plex_artist_count")
            ).scalar_one_or_none()
            now = datetime.utcnow()
            if setting is None:
                setting = Setting(key="plex_artist_count", value=str(artist_count), created_at=now, updated_at=now)
                session.add(setting)
            else:
                setting.value = str(artist_count)
                setting.updated_at = now
            session.commit()
        finally:
            session.close()
