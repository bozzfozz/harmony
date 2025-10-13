"""Workers responsible for metadata management."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Download, DownloadState
from app.utils import metadata_utils

logger = get_logger(__name__)


@dataclass(slots=True)
class MetadataJob:
    """Payload queued for metadata enrichment."""

    download_id: int
    audio_path: Path
    payload: Mapping[str, Any]
    request_payload: Mapping[str, Any]
    result: asyncio.Future[dict[str, Any]]


class MetadataWorker:
    """Enrich completed downloads with rich metadata and persist the result."""

    def __init__(
        self,
        *,
        spotify_client: SpotifyClient | None = None,
    ) -> None:
        self._spotify = spotify_client
        metadata_utils.SPOTIFY_CLIENT = spotify_client
        self._queue: asyncio.Queue[MetadataJob | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        await self._queue.put(None)
        if self._task is not None:
            try:
                await self._task
            finally:
                self._task = None

    async def enqueue(
        self,
        download_id: int,
        audio_path: Path,
        *,
        payload: Mapping[str, Any] | None = None,
        request_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        job = MetadataJob(
            download_id=download_id,
            audio_path=audio_path,
            payload=dict(payload or {}),
            request_payload=dict(request_payload or {}),
            result=future,
        )
        if not self._running:
            try:
                metadata = await self._process_job(job)
            except Exception as exc:
                future.set_exception(exc)
                raise
            else:
                future.set_result(metadata)
            return await future

        await self._queue.put(job)
        return await future

    async def wait_for_pending(self) -> None:
        await self._queue.join()

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            try:
                metadata = await self._process_job(job)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Metadata enrichment failed for %s: %s", job.download_id, exc)
                if not job.result.done():
                    job.result.set_exception(exc)
            else:
                if not job.result.done():
                    job.result.set_result(metadata)
            finally:
                self._queue.task_done()

    async def _process_job(self, job: MetadataJob) -> dict[str, Any]:
        metadata = await self._collect_metadata(job)

        try:
            await asyncio.to_thread(metadata_utils.write_metadata_tags, job.audio_path, metadata)
        except FileNotFoundError:
            logger.debug(
                "Audio file missing for download %s: %s",
                job.download_id,
                job.audio_path,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Failed to persist metadata for download %s: %s", job.download_id, exc)

        self._persist_metadata(job.download_id, metadata)
        return metadata

    async def _collect_metadata(self, job: MetadataJob) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        metadata.update(self._extract_metadata_from_payload(job.request_payload))
        metadata.update(self._extract_metadata_from_payload(job.payload))

        spotify_id = self._extract_spotify_id(job.request_payload)
        if not spotify_id:
            spotify_id = self._extract_spotify_id(job.payload)
        if spotify_id:
            spotify_metadata = await asyncio.to_thread(
                metadata_utils.extract_metadata_from_spotify, spotify_id
            )
            for key, value in spotify_metadata.items():
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    metadata[key] = text

        return metadata

    def _persist_metadata(self, download_id: int, metadata: Mapping[str, Any]) -> None:
        relevant_keys = {"genre", "composer", "producer", "isrc", "copyright"}
        with session_scope() as session:
            download = session.get(Download, download_id)
            if download is None:
                return
            updated = False
            for key in relevant_keys:
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    if getattr(download, key, None) != value:
                        setattr(download, key, value)
                        updated = True
            artwork_url = metadata.get("artwork_url")
            if isinstance(artwork_url, str) and artwork_url:
                if download.artwork_url != artwork_url:
                    download.artwork_url = artwork_url
                    updated = True
            if updated:
                download.updated_at = datetime.utcnow()
            session.add(download)

    @staticmethod
    def _extract_metadata_from_payload(
        payload: Mapping[str, Any] | None,
    ) -> dict[str, str]:
        metadata: dict[str, str] = {}
        if not isinstance(payload, Mapping):
            return metadata
        keys = ("genre", "composer", "producer", "isrc", "artwork_url", "copyright")
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str | int | float):
                text = str(value).strip()
                if text:
                    metadata[key] = text
        nested = payload.get("metadata")
        if isinstance(nested, Mapping):
            nested_metadata = MetadataWorker._extract_metadata_from_payload(nested)
            for key, value in nested_metadata.items():
                metadata.setdefault(key, value)
        return metadata

    @staticmethod
    def _extract_spotify_id(payload: Mapping[str, Any] | None) -> str | None:
        if not isinstance(payload, Mapping):
            return None
        keys = (
            "spotify_id",
            "spotifyId",
            "spotify_track_id",
            "spotifyTrackId",
            "spotify_track",
        )
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, Mapping):
                nested = value.get("id")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
        nested_track = payload.get("track")
        if isinstance(nested_track, Mapping):
            candidate = nested_track.get("spotify_id") or nested_track.get("id")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None


class MetadataUpdateWorker:
    """Manage ad-hoc metadata refresh jobs across stored downloads."""

    def __init__(
        self,
        metadata_worker: MetadataWorker | None = None,
        *,
        session_factory: Callable[[], AbstractContextManager[Any]] = session_scope,
        matching_worker: Any | None = None,
    ) -> None:
        self._metadata_worker = metadata_worker
        self._session_factory = session_factory
        self._matching_worker = matching_worker
        self._status_lock = asyncio.Lock()
        self._status: dict[str, Any] = self._initial_status()
        self._job_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> dict[str, Any]:
        """Start (or return) the current metadata refresh job status."""

        if self._metadata_worker is None:
            raise RuntimeError("Metadata worker unavailable")

        async with self._status_lock:
            if self._job_task is not None and not self._job_task.done():
                return self._snapshot_locked()

        jobs = await asyncio.to_thread(self._collect_jobs)
        now = datetime.now(UTC)

        if not jobs:
            async with self._status_lock:
                self._status.update(
                    {
                        "status": "completed",
                        "phase": "No eligible downloads",
                        "processed": 0,
                        "total": 0,
                        "started_at": None,
                        "completed_at": now,
                        "error": None,
                        "current_download_id": None,
                        "last_completed_id": None,
                        "last_failed_id": None,
                    }
                )
            return await self.status()

        async with self._status_lock:
            self._stop_event.clear()
            self._status.update(
                {
                    "status": "running",
                    "phase": "Refreshing metadata",
                    "processed": 0,
                    "total": len(jobs),
                    "started_at": now,
                    "completed_at": None,
                    "error": None,
                    "current_download_id": None,
                    "last_completed_id": None,
                    "last_failed_id": None,
                }
            )
            loop = asyncio.get_running_loop()
            self._job_task = loop.create_task(self._run_job(jobs))

        return await self.status()

    async def stop(self) -> dict[str, Any]:
        """Request the active job to stop and return the latest status."""

        task: asyncio.Task[None] | None
        async with self._status_lock:
            task = self._job_task
            running = task is not None and not task.done()

        if not running:
            return await self.status()

        self._stop_event.set()
        if task is None:
            raise RuntimeError("Metadata refresh task missing despite running state.")
        await task
        return await self.status()

    async def status(self) -> dict[str, Any]:
        """Return a snapshot of the current worker state."""

        async with self._status_lock:
            snapshot = self._snapshot_locked()

        snapshot["matching_queue"] = self._matching_queue_size()
        return snapshot

    def _matching_queue_size(self) -> int:
        queue = getattr(self._matching_worker, "queue", None)
        if queue is None or not hasattr(queue, "qsize"):
            return 0
        try:
            return max(int(queue.qsize()), 0)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Unable to inspect matching queue: %s", exc)
            return 0

    def _snapshot_locked(self) -> dict[str, Any]:
        data = dict(self._status)
        data["started_at"] = self._format_dt(data.get("started_at"))
        data["completed_at"] = self._format_dt(data.get("completed_at"))
        return data

    def _collect_jobs(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        with self._session_factory() as session:
            query = (
                session.query(Download)
                .filter(Download.state == DownloadState.COMPLETED.value)
                .order_by(Download.id.asc())
            )
            for record in query:
                file_path = self._resolve_file_path(record)
                if file_path is None:
                    continue
                jobs.append(
                    {
                        "download_id": record.id,
                        "file_path": file_path,
                        "payload": self._build_payload(record),
                        "request_payload": dict(record.request_payload or {}),
                    }
                )
        return jobs

    async def _run_job(self, jobs: Iterable[dict[str, Any]]) -> None:
        processed = 0
        try:
            for job in jobs:
                if self._stop_event.is_set():
                    await self._update_status(
                        status="stopped",
                        phase="Stop requested",
                        completed_at=datetime.now(UTC),
                        current_download_id=None,
                    )
                    return

                download_id = job["download_id"]
                await self._update_status(current_download_id=download_id)

                try:
                    await self._metadata_worker.enqueue(  # type: ignore[union-attr]
                        download_id,
                        job["file_path"],
                        payload=job["payload"],
                        request_payload=job["request_payload"],
                    )
                except Exception as exc:
                    processed += 1
                    logger.exception(
                        "Metadata refresh failed for download %s: %s", download_id, exc
                    )
                    await self._update_status(
                        processed=processed,
                        error=str(exc),
                        last_failed_id=download_id,
                    )
                    continue

                processed += 1
                await self._update_status(
                    processed=processed,
                    error=None,
                    last_completed_id=download_id,
                )

            await self._update_status(
                status="completed",
                phase="Refresh complete",
                completed_at=datetime.now(UTC),
                current_download_id=None,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Metadata update job crashed: %s", exc)
            await self._update_status(
                status="failed",
                phase="Job failed",
                error=str(exc),
                completed_at=datetime.now(UTC),
                current_download_id=None,
            )
        finally:
            async with self._status_lock:
                self._job_task = None
                self._stop_event.clear()

    async def _update_status(self, **fields: Any) -> None:
        async with self._status_lock:
            self._status.update(fields)

    @staticmethod
    def _resolve_file_path(record: Download) -> Path | None:
        candidate = record.organized_path or record.filename
        if not candidate:
            return None
        return Path(candidate)

    @staticmethod
    def _build_payload(record: Download) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field_name in (
            "genre",
            "composer",
            "producer",
            "isrc",
            "copyright",
            "artwork_url",
        ):
            value = getattr(record, field_name, None)
            if isinstance(value, str) and value:
                payload[field_name] = value
        return payload

    @staticmethod
    def _format_dt(value: Any) -> str | None:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.isoformat()
        return None

    @staticmethod
    def _initial_status() -> dict[str, Any]:
        return {
            "status": "idle",
            "phase": "Idle",
            "processed": 0,
            "total": 0,
            "started_at": None,
            "completed_at": None,
            "error": None,
            "current_download_id": None,
            "last_completed_id": None,
            "last_failed_id": None,
        }
