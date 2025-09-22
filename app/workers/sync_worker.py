"""Background worker for processing Soulseek download jobs."""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.core.soulseek_client import SoulseekClient
from app.db import SessionLocal
from app.logging import get_logger
from app.models import Download

logger = get_logger(__name__)


class SyncWorker:
    def __init__(self, soulseek_client: SoulseekClient) -> None:
        self._client = soulseek_client
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running = asyncio.Event()

    @property
    def queue(self) -> asyncio.Queue[Dict[str, Any]]:
        return self._queue

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._running.set()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running.clear()
        if self._task:
            await self._queue.put({"_shutdown": True})
            await self._task

    async def _run(self) -> None:
        logger.info("SyncWorker started")
        while self._running.is_set():
            job = await self._queue.get()
            try:
                if job.get("_shutdown"):
                    break
                await self._process_job(job)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Failed to process sync job: %s", exc)
            finally:
                self._queue.task_done()
        logger.info("SyncWorker stopped")

    async def _process_job(self, job: Dict[str, Any]) -> None:
        username = job.get("username")
        files = job.get("files", [])
        if not username or not files:
            logger.warning("Invalid download job received: %s", job)
            return
        await self._client.download({"username": username, "files": files})
        self._store_download(job)

    def _store_download(self, job: Dict[str, Any]) -> None:
        session: Session = SessionLocal()
        try:
            for file_info in job.get("files", []):
                download = Download(
                    filename=file_info.get("filename", "unknown"),
                    state="queued",
                    progress=0.0,
                )
                session.add(download)
            session.commit()
        finally:
            session.close()
