"""Worker that periodically scans the Plex library."""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime

from sqlalchemy import select

from app.core.plex_client import PlexClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Setting
from app.utils.activity import record_activity, record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.settings_store import read_setting, write_setting
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat

logger = get_logger(__name__)

DEFAULT_INTERVAL = 600


class ScanWorker:
    def __init__(self, plex_client: PlexClient, interval_seconds: int = DEFAULT_INTERVAL) -> None:
        self._client = plex_client
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._failure_count = 0

    async def start(self) -> None:
        if self._task is None or self._task.done():
            record_worker_started("scan")
            self._running.set()
            self._stop_event = asyncio.Event()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        self._stop_event.set()
        if self._task:
            await self._task

    async def _run(self) -> None:
        logger.info("ScanWorker started")
        write_setting("worker.scan.last_start", datetime.utcnow().isoformat())
        record_worker_heartbeat("scan")
        try:
            while self._running.is_set():
                self._interval = self._resolve_interval()
                await self._perform_scan()
                self._record_heartbeat()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    continue
        finally:
            write_setting("worker.scan.last_stop", datetime.utcnow().isoformat())
            mark_worker_status("scan", WORKER_STOPPED)
            record_worker_stopped("scan")
            logger.info("ScanWorker stopped")

    async def run_once(self) -> None:
        """Execute a single scan cycle on demand."""

        await self._perform_scan()
        self._record_heartbeat()

    async def _perform_scan(self) -> None:
        start = time.perf_counter()
        incremental = False
        if self._is_incremental_enabled():
            incremental = await self._trigger_incremental_scan()

        try:
            stats = await self._client.get_library_statistics()
        except Exception as exc:  # pragma: no cover
            self._failure_count += 1
            logger.error("Failed to scan Plex library: %s", exc)
            if self._failure_count >= 3:
                record_activity(
                    "metadata",
                    "scan_failed",
                    details={"error": str(exc), "consecutive": self._failure_count},
                )
            return

        self._failure_count = 0
        artist_count = stats.get("artists", 0)
        album_count = stats.get("albums", 0)
        track_count = stats.get("tracks", 0)

        now = datetime.utcnow()
        with session_scope() as session:
            self._upsert_setting(session, "plex_artist_count", str(artist_count), now)
            self._upsert_setting(session, "plex_album_count", str(album_count), now)
            self._upsert_setting(session, "plex_track_count", str(track_count), now)
            self._upsert_setting(
                session, "plex_last_scan", now.isoformat(timespec="seconds"), now
            )
        duration_ms = int((time.perf_counter() - start) * 1000)
        write_setting("metrics.scan.duration_ms", str(duration_ms))
        write_setting("metrics.scan.incremental", "1" if incremental else "0")
        logger.info(
            "Plex scan complete: %d artists, %d albums, %d tracks (incremental=%s)",
            artist_count,
            album_count,
            track_count,
            incremental,
        )

    def _resolve_interval(self) -> int:
        setting_value = read_setting("scan_worker_interval_seconds")
        env_value = os.getenv("SCAN_WORKER_INTERVAL_SECONDS")
        for value in (setting_value, env_value):
            if not value:
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                write_setting("metrics.scan.interval", str(parsed))
                return parsed
        write_setting("metrics.scan.interval", str(DEFAULT_INTERVAL))
        return DEFAULT_INTERVAL

    def _is_incremental_enabled(self) -> bool:
        setting_value = read_setting("scan_worker_incremental")
        if setting_value is not None:
            return setting_value.lower() in {"1", "true", "yes"}
        env_value = os.getenv("SCAN_WORKER_INCREMENTAL", "0")
        return env_value.lower() in {"1", "true", "yes"}

    async def _trigger_incremental_scan(self) -> bool:
        try:
            libraries = await self._client.get_libraries()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Unable to list Plex libraries for incremental scan: %s", exc)
            return False

        triggered = False
        container = libraries.get("MediaContainer", {}) if isinstance(libraries, dict) else {}
        for section in container.get("Directory", []) or []:
            if not isinstance(section, dict):
                continue
            if section.get("type") != "artist":
                continue
            section_id = section.get("key")
            if not section_id:
                continue
            try:
                await self._client.refresh_library_section(str(section_id), full=False)
                triggered = True
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Failed to trigger incremental scan for section %s: %s", section_id, exc)
        return triggered

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

    def _record_heartbeat(self) -> None:
        record_worker_heartbeat("scan")
