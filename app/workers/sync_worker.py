"""Background worker for processing Soulseek download jobs."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Iterable

from app.core.soulseek_client import SoulseekClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Download

logger = get_logger(__name__)

ALLOWED_STATES = {"queued", "downloading", "completed", "failed"}


class SyncWorker:
    def __init__(self, soulseek_client: SoulseekClient) -> None:
        self._client = soulseek_client
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running = asyncio.Event()
        self._poll_interval = 2.0

    @property
    def queue(self) -> asyncio.Queue[Dict[str, Any]]:
        return self._queue

    def is_running(self) -> bool:
        return self._running.is_set() and self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._running.set()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running.clear()
        if self._task:
            await self._queue.put({"_shutdown": True})
            await self._task

    async def enqueue(self, job: Dict[str, Any]) -> None:
        """Submit a download job for processing."""

        if self.is_running():
            await self._queue.put(job)
            return
        await self._process_job(job)
        await self.refresh_downloads()

    async def _run(self) -> None:
        logger.info("SyncWorker started")
        try:
            while self._running.is_set():
                job: Dict[str, Any] | None = None
                try:
                    job = await asyncio.wait_for(self._queue.get(), timeout=self._poll_interval)
                except asyncio.TimeoutError:
                    await self.refresh_downloads()
                    continue

                try:
                    if job.get("_shutdown"):
                        break
                    await self._process_job(job)
                    await self.refresh_downloads()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("Failed to process sync job: %s", exc)
                finally:
                    self._queue.task_done()
        finally:
            self._running.clear()
            logger.info("SyncWorker stopped")

    async def _process_job(self, job: Dict[str, Any]) -> None:
        username = job.get("username")
        files = job.get("files", [])
        if not username or not files:
            logger.warning("Invalid download job received: %s", job)
            return

        try:
            await self._client.download({"username": username, "files": files})
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to queue Soulseek download: %s", exc)
            self._mark_failed(files)
            raise

    async def refresh_downloads(self) -> None:
        """Poll Soulseek for download progress and persist it."""

        try:
            response = await self._client.get_download_status()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Unable to obtain Soulseek download status: %s", exc)
            return

        downloads: Iterable[Dict[str, Any]]
        if isinstance(response, dict):
            downloads = response.get("downloads", []) or []
        elif isinstance(response, list):
            downloads = response
        else:  # pragma: no cover - defensive
            downloads = []

        if not downloads:
            return

        with session_scope() as session:
            for payload in downloads:
                download_id = payload.get("download_id") or payload.get("id")
                if download_id is None:
                    continue

                download = session.get(Download, int(download_id))
                if download is None:
                    continue

                state = str(payload.get("state", download.state))
                if state not in ALLOWED_STATES:
                    state = download.state

                progress_value = payload.get("progress", download.progress)
                try:
                    progress = float(progress_value)
                except (TypeError, ValueError):
                    progress = download.progress

                if progress < 0:
                    progress = 0.0
                elif progress > 100:
                    progress = 100.0

                if state == "queued" and 0 < progress < 100:
                    state = "downloading"
                elif state == "completed":
                    progress = 100.0

                download.state = state
                download.progress = progress
                download.updated_at = datetime.utcnow()

    def _mark_failed(self, files: Iterable[Dict[str, Any]]) -> None:
        download_ids = []
        for file_info in files:
            identifier = file_info.get("download_id") or file_info.get("id")
            if identifier is not None:
                download_ids.append(int(identifier))

        if not download_ids:
            return

        with session_scope() as session:
            for download_id in download_ids:
                download = session.get(Download, download_id)
                if download is None:
                    continue
                download.state = "failed"
                download.updated_at = datetime.utcnow()
