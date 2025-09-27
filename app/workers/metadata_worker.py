"""Workers responsible for metadata management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.models import Download
from app.utils import metadata_utils

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
                logger.exception("Metadata enrichment failed for %s: %s", job.download_id, exc)
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


class MetadataUpdateWorker:
    """Placeholder worker while the legacy metadata refresh is archived."""

    def __init__(self, matching_worker: Any | None = None) -> None:
        self._matching_worker = matching_worker

    async def start(self) -> Dict[str, Any]:
        """Return the disabled status for compatibility with old callers."""

        logger.info("Metadata update requested but legacy integration is disabled")
        return self.status()

    async def stop(self) -> Dict[str, Any]:
        """Return the disabled status for compatibility with old callers."""

        logger.info("Metadata update stop requested but legacy integration is disabled")
        return self.status()

    def status(self) -> Dict[str, Any]:
        """Expose a stable payload indicating that the worker is disabled."""

        queue_size = 0
        queue = getattr(self._matching_worker, "queue", None)
        if queue is not None and hasattr(queue, "qsize"):
            try:
                queue_size = int(queue.qsize())
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.debug("Unable to inspect matching queue while disabled: %s", exc)

        return {
            "status": "disabled",
            "phase": "Legacy integration archived",
            "processed": 0,
            "matching_queue": max(queue_size, 0),
            "started_at": None,
            "completed_at": None,
            "error": "metadata update disabled",
        }
