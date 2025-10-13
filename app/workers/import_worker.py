"""Background worker that fans out playlist import requests to ingest services."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.logging import get_logger
from app.models import ImportBatch, ImportSession
from app.services.free_ingest_service import FreeIngestService
from app.utils.activity import record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat

logger = get_logger(__name__)


@dataclass(slots=True)
class ImportJob:
    """Represents a queued playlist import job."""

    session_id: str
    playlist_id: str


PlaylistLinks = Sequence[str]


class ImportWorker:
    """Dispatch playlist import jobs to the configured ingest backend."""

    def __init__(
        self,
        *,
        free_ingest_service: FreeIngestService | None = None,
        service_factory: Callable[[], FreeIngestService] | None = None,
    ) -> None:
        if free_ingest_service is None and service_factory is None:
            raise ValueError("free_ingest_service or service_factory must be provided")
        self._service = free_ingest_service
        self._service_factory = service_factory
        self._queue: asyncio.Queue[ImportJob | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._running = asyncio.Event()

    async def start(self) -> None:
        """Start the background worker loop."""

        if self._task is not None and not self._task.done():
            return
        record_worker_started("import")
        mark_worker_status("import", "starting")
        self._running.set()
        self._task = asyncio.create_task(self._run(), name="import-worker")

    async def stop(self) -> None:
        """Stop the worker loop and wait for shutdown."""

        if self._task is None:
            return
        if self._running.is_set():
            self._running.clear()
            await self._queue.put(None)
        try:
            await self._task
        finally:
            self._task = None

    async def enqueue(self, jobs: Iterable[ImportJob]) -> None:
        """Queue one or more import jobs for processing."""

        pending = [job for job in jobs]
        if not pending:
            return

        if not self._running.is_set():
            for job in pending:
                await self._handle_job(job)
            return

        for job in pending:
            await self._queue.put(job)

    async def _run(self) -> None:
        logger.info("ImportWorker started")
        mark_worker_status("import", "running")
        record_worker_heartbeat("import")
        try:
            while True:
                job = await self._queue.get()
                if job is None:
                    self._queue.task_done()
                    break
                try:
                    await self._handle_job(job)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.exception(
                        "Import job failed for session=%s playlist=%s: %s",
                        job.session_id,
                        job.playlist_id,
                        exc,
                    )
                finally:
                    record_worker_heartbeat("import")
                    self._queue.task_done()
        except asyncio.CancelledError:  # pragma: no cover - cooperative cancellation
            logger.debug("ImportWorker task cancelled")
            raise
        finally:
            self._running.clear()
            mark_worker_status("import", WORKER_STOPPED)
            record_worker_stopped("import")
            logger.info("ImportWorker stopped")

    async def _handle_job(self, job: ImportJob) -> None:
        logger.info(
            "Processing playlist import job session=%s playlist=%s",
            job.session_id,
            job.playlist_id,
        )
        self._update_batch_state(job, "processing")
        service = self._resolve_service()
        playlist_links = self._resolve_playlist_links(job)
        try:
            submission = await service.submit(playlist_links=playlist_links)
        except Exception:
            self._update_batch_state(job, "failed")
            raise
        else:
            self._update_batch_state(job, "completed")
            logger.info(
                "Playlist import completed session=%s playlist=%s ingest_job=%s",
                job.session_id,
                job.playlist_id,
                submission.job_id,
            )

    def _resolve_service(self) -> FreeIngestService:
        if self._service is None and self._service_factory is not None:
            self._service = self._service_factory()
        if self._service is None:
            raise RuntimeError("Free ingest service not available")
        return self._service

    @staticmethod
    def _resolve_playlist_links(job: ImportJob) -> PlaylistLinks:
        canonical = f"https://open.spotify.com/playlist/{job.playlist_id}"
        return (canonical,)

    def _update_batch_state(self, job: ImportJob, state: str) -> None:
        with session_scope() as session:
            batch = self._load_batch(session, job)
            if batch is None:
                logger.warning(
                    "Import batch not found for session=%s playlist=%s",
                    job.session_id,
                    job.playlist_id,
                )
                return
            batch.state = state
            session.add(batch)
            self._update_session_state(session, job.session_id, state)

    def _load_batch(self, session: Session, job: ImportJob) -> ImportBatch | None:
        return (
            session.execute(
                select(ImportBatch)
                .where(ImportBatch.session_id == job.session_id)
                .where(ImportBatch.playlist_id == job.playlist_id)
            )
            .scalars()
            .first()
        )

    def _update_session_state(self, session: Session, session_id: str, state: str) -> None:
        record = session.get(ImportSession, session_id)
        if record is None:
            return
        if state == "processing":
            if record.state not in {"failed", "completed"}:
                record.state = "processing"
            session.add(record)
            return
        if state == "failed":
            record.state = "failed"
            session.add(record)
            return
        if state == "completed":
            pending = session.execute(
                select(func.count())
                .select_from(ImportBatch)
                .where(ImportBatch.session_id == session_id)
                .where(ImportBatch.state != "completed")
            ).scalar_one()
            record.state = "completed" if int(pending or 0) == 0 else "processing"
            session.add(record)


__all__ = ["ImportJob", "ImportWorker"]
