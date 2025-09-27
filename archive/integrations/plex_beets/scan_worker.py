"""Worker dedicated to triggering Plex scans and recording lightweight metrics."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from typing import Dict

from app.core.plex_client import PlexClient, PlexClientError
from app.db import session_scope
from app.logging import get_logger
from app.models import Setting
from app.utils.activity import record_activity, record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.settings_store import read_setting, write_setting
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat

logger = get_logger(__name__)

DEFAULT_INTERVAL = 600
SCAN_DEDUPE_TTL = 60


class ScanWorker:
    """Serialises Plex scans per library section with lightweight deduplication."""

    def __init__(
        self,
        plex_client: PlexClient,
        interval_seconds: int = DEFAULT_INTERVAL,
        *,
        dedupe_ttl_seconds: int = SCAN_DEDUPE_TTL,
    ) -> None:
        self._client = plex_client
        self._interval = interval_seconds
        self._dedupe_ttl = max(1, dedupe_ttl_seconds)
        self._task: asyncio.Task | None = None
        self._running = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._recent_requests: Dict[str, float] = {}
        self._recent_lock = asyncio.Lock()
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

    async def request_scan(self, section_id: str | None = None) -> bool:
        """Request an incremental scan for the given section id."""

        target = section_id or await self._client.default_music_section()
        if not target:
            logger.debug("No Plex section available for scan request")
            return False

        now = time.monotonic()
        async with self._recent_lock:
            self._prune_recent(now)
            last = self._recent_requests.get(target)
            if last and now - last < self._dedupe_ttl:
                logger.debug("Deduplicated Plex scan request for section %s", target)
                return False
            self._recent_requests[target] = now

        if self._running.is_set():
            await self._queue.put(target)
            return True

        await self._execute_scan(target)
        return True

    async def run_once(self) -> None:
        """Collect current Plex statistics immediately."""

        await self._collect_statistics()
        self._record_heartbeat()

    async def _run(self) -> None:
        logger.info("ScanWorker started")
        write_setting("worker.scan.last_start", datetime.utcnow().isoformat())
        record_worker_heartbeat("scan")
        try:
            while self._running.is_set():
                timeout = self._resolve_interval()
                try:
                    section_id = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    await self._collect_statistics()
                    self._record_heartbeat()
                    continue

                try:
                    await self._execute_scan(section_id)
                except PlexClientError as exc:
                    logger.warning("Plex scan request failed for section %s: %s", section_id, exc)
                except Exception as exc:  # pragma: no cover - defensive guard
                    logger.exception(
                        "Unexpected Plex scan failure for section %s: %s", section_id, exc
                    )
                finally:
                    self._record_heartbeat()
                    self._queue.task_done()

                if self._stop_event.is_set():
                    break
        finally:
            write_setting("worker.scan.last_stop", datetime.utcnow().isoformat())
            mark_worker_status("scan", WORKER_STOPPED)
            record_worker_stopped("scan")
            logger.info("ScanWorker stopped")

    async def _execute_scan(self, section_id: str) -> None:
        start = time.perf_counter()
        await self._client.refresh_library_section(section_id, full=False)
        duration_ms = int((time.perf_counter() - start) * 1000)
        write_setting("metrics.scan.incremental", "1")
        write_setting("metrics.scan.last_trigger_ms", str(duration_ms))
        logger.info(
            "Triggered Plex scan",
            extra={
                "event": "plex_scan_enqueue",
                "target": "plex",
                "section_id": section_id,
                "duration_ms": duration_ms,
            },
        )

    async def _collect_statistics(self) -> None:
        start = time.perf_counter()
        try:
            stats = await self._client.get_library_statistics()
        except Exception as exc:  # pragma: no cover - defensive guard
            self._failure_count += 1
            logger.error("Failed to refresh Plex library statistics: %s", exc)
            if self._failure_count >= 3:
                record_activity(
                    "metadata",
                    "scan_failed",
                    details={"error": str(exc), "consecutive": self._failure_count},
                )
            return

        self._failure_count = 0
        now = datetime.utcnow()
        with session_scope() as session:
            self._upsert_setting(session, "plex_artist_count", str(stats.get("artists", 0)), now)
            self._upsert_setting(session, "plex_album_count", str(stats.get("albums", 0)), now)
            self._upsert_setting(session, "plex_track_count", str(stats.get("tracks", 0)), now)
            self._upsert_setting(session, "plex_last_scan", now.isoformat(timespec="seconds"), now)

        duration_ms = int((time.perf_counter() - start) * 1000)
        write_setting("metrics.scan.duration_ms", str(duration_ms))
        write_setting("metrics.scan.incremental", "0")
        logger.info(
            "Plex statistics refreshed",
            extra={
                "event": "plex_scan_ok",
                "target": "plex",
                "duration_ms": duration_ms,
                "stats": stats,
            },
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

    @staticmethod
    def _upsert_setting(session, key: str, value: str, timestamp: datetime) -> None:
        setting = session.query(Setting).filter(Setting.key == key).one_or_none()
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

    def _prune_recent(self, now: float) -> None:
        expired = [
            section for section, ts in self._recent_requests.items() if now - ts >= self._dedupe_ttl
        ]
        for section in expired:
            self._recent_requests.pop(section, None)
