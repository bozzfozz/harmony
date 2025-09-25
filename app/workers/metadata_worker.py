"""Workers responsible for metadata management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.core.plex_client import PlexClient
from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Download
from app.utils import metadata_utils
from app.workers.scan_worker import ScanWorker

logger = get_logger(__name__)


@dataclass(slots=True)
class MetadataJob:
    """Payload queued for metadata enrichment."""

    download_id: int
    audio_path: Path
    payload: Mapping[str, Any]
    request_payload: Mapping[str, Any]
    result: asyncio.Future[Dict[str, Any]]


class MetadataWorker:
    """Enrich completed downloads with rich metadata and persist the result."""

    def __init__(
        self,
        *,
        spotify_client: SpotifyClient | None = None,
        plex_client: PlexClient | None = None,
    ) -> None:
        self._spotify = spotify_client
        self._plex = plex_client
        metadata_utils.SPOTIFY_CLIENT = spotify_client
        metadata_utils.PLEX_CLIENT = plex_client
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
    ) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Dict[str, Any]] = loop.create_future()
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
                logger.exception(
                    "Metadata enrichment failed for %s: %s", job.download_id, exc
                )
                if not job.result.done():
                    job.result.set_exception(exc)
            else:
                if not job.result.done():
                    job.result.set_result(metadata)
            finally:
                self._queue.task_done()

    async def _process_job(self, job: MetadataJob) -> Dict[str, Any]:
        metadata = await self._collect_metadata(job)

        try:
            await asyncio.to_thread(
                metadata_utils.write_metadata_tags, job.audio_path, metadata
            )
        except FileNotFoundError:
            logger.debug(
                "Audio file missing for download %s: %s",
                job.download_id,
                job.audio_path,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                "Failed to persist metadata for download %s: %s", job.download_id, exc
            )

        self._persist_metadata(job.download_id, metadata)
        return metadata

    async def _collect_metadata(self, job: MetadataJob) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
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

        plex_id = self._extract_plex_id(job.request_payload)
        if not plex_id:
            plex_id = self._extract_plex_id(job.payload)
        if plex_id and self._plex is not None:
            try:
                plex_payload = await self._plex.get_track_metadata(str(plex_id))
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("Plex metadata lookup failed for %s: %s", plex_id, exc)
            else:
                plex_metadata = metadata_utils.extract_metadata_from_plex(plex_payload)
                for key, value in plex_metadata.items():
                    if value is None:
                        continue
                    text = str(value).strip()
                    if text:
                        metadata.setdefault(key, text)

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
    ) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        if not isinstance(payload, Mapping):
            return metadata
        keys = ("genre", "composer", "producer", "isrc", "artwork_url", "copyright")
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (str, int, float)):
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
    def _extract_spotify_id(payload: Mapping[str, Any] | None) -> Optional[str]:
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

    @staticmethod
    def _extract_plex_id(payload: Mapping[str, Any] | None) -> Optional[str]:
        if not isinstance(payload, Mapping):
            return None
        for key in ("plex_id", "plexId", "plex_rating_key", "ratingKey", "rating_key"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = payload.get("metadata")
        if isinstance(nested, Mapping):
            candidate = nested.get("ratingKey") or nested.get("id")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None


class MetadataUpdateRunningError(RuntimeError):
    """Raised when a metadata update is already running."""


class MetadataUpdateWorker:
    """Trigger on-demand metadata refreshes using existing workers."""

    def __init__(
        self,
        scan_worker: ScanWorker,
        matching_worker: Any | None = None,
    ) -> None:
        self._scan_worker = scan_worker
        self._matching_worker = matching_worker
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._stop_requested = False
        self._state: Dict[str, Any] = {
            "status": "idle",
            "phase": "Idle",
            "processed": 0,
            "matching_queue": 0,
            "started_at": None,
            "completed_at": None,
            "error": None,
        }

    async def start(self) -> Dict[str, Any]:
        """Begin a new metadata update cycle."""

        async with self._lock:
            if self._task and not self._task.done():
                raise MetadataUpdateRunningError()

            self._stop_requested = False
            self._state.update(
                status="running",
                phase="Preparing",
                processed=0,
                error=None,
                started_at=datetime.now(timezone.utc),
                completed_at=None,
            )
            logger.info("Metadata update started")
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run())
            return self._snapshot()

    async def stop(self) -> Dict[str, Any]:
        """Request graceful shutdown of the current metadata update."""

        if self._task and not self._task.done():
            self._stop_requested = True
            self._state.update(status="stopping", phase="Stopping current task")
            logger.info("Stop requested for metadata update")
        return self._snapshot()

    def status(self) -> Dict[str, Any]:
        """Return a serialisable view of the current state."""

        return self._snapshot()

    async def _run(self) -> None:
        try:
            await self._scan_phase()
            if self._stop_requested:
                self._finish("stopped", "Stopped by user")
                return
            await self._matching_phase()
            if self._stop_requested:
                self._finish("stopped", "Stopped by user")
                return
            self._finish("completed", "Completed")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Metadata update failed: %s", exc)
            self._state.update(
                status="error",
                phase="Error",
                error=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
        finally:
            self._task = None
            self._stop_requested = False

    async def _scan_phase(self) -> None:
        self._state.update(phase="Scanning library")
        await self._scan_worker.run_once()
        self._state["processed"] += 1

    async def _matching_phase(self) -> None:
        self._state.update(phase="Reconciling matches")
        queue = getattr(self._matching_worker, "queue", None)
        queue_size = 0
        if queue is not None and hasattr(queue, "qsize"):
            try:
                queue_size = int(queue.qsize())
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("Unable to inspect matching queue: %s", exc)
        self._state["matching_queue"] = max(queue_size, 0)
        await asyncio.sleep(0)

    def _finish(self, status: str, phase: str) -> None:
        self._state.update(
            status=status,
            phase=phase,
            completed_at=datetime.now(timezone.utc),
        )
        logger.info("Metadata update finished with status %s", status)

    def _snapshot(self) -> Dict[str, Any]:
        state = dict(self._state)
        for key in ("started_at", "completed_at"):
            value = state.get(key)
            if isinstance(value, datetime):
                state[key] = value.isoformat()
            elif value is None:
                state[key] = None
        return state
