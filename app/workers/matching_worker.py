"""Background worker handling deferred matching operations."""
from __future__ import annotations

import asyncio
import os
import statistics
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

from app.core.matching_engine import MusicMatchingEngine
from app.db import session_scope
from app.logging import get_logger
from app.models import Match
from app.utils.activity import record_activity, record_worker_started, record_worker_stopped
from app.utils.events import WORKER_STOPPED
from app.utils.settings_store import (
    increment_counter,
    read_setting,
    write_setting,
)
from app.utils.worker_health import mark_worker_status, record_worker_heartbeat
from app.workers.persistence import PersistentJobQueue, QueuedJob

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 5
DEFAULT_THRESHOLD = 0.65


class MatchingWorker:
    def __init__(
        self,
        engine: MusicMatchingEngine,
        *,
        batch_size: int | None = None,
        confidence_threshold: float | None = None,
        batch_wait_seconds: float = 0.1,
    ) -> None:
        self._engine = engine
        self._job_store = PersistentJobQueue("matching")
        self._queue: asyncio.Queue[QueuedJob | None] = asyncio.Queue()
        self._manager_task: asyncio.Task | None = None
        self._worker_task: asyncio.Task | None = None
        self._running = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._batch_wait = batch_wait_seconds
        self._batch_size = max(1, batch_size or self._resolve_batch_size())
        self._confidence_threshold = confidence_threshold or self._resolve_threshold()

    def _resolve_batch_size(self) -> int:
        setting_value = read_setting("matching_worker_batch_size")
        env_value = os.getenv("MATCHING_WORKER_BATCH_SIZE")
        for value in (setting_value, env_value):
            if not value:
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return DEFAULT_BATCH_SIZE

    def _resolve_threshold(self) -> float:
        setting_value = read_setting("matching_confidence_threshold")
        env_value = os.getenv("MATCHING_CONFIDENCE_THRESHOLD")
        for value in (setting_value, env_value):
            if not value:
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if 0 < parsed <= 1:
                return parsed
        return DEFAULT_THRESHOLD

    async def start(self) -> None:
        if self._manager_task is not None and not self._manager_task.done():
            return
        record_worker_started("matching")
        self._running.set()
        self._stop_event = asyncio.Event()
        self._manager_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._running.is_set():
            return
        self._stop_event.set()
        if self._manager_task is not None:
            await self._manager_task

    @property
    def queue(self) -> asyncio.Queue[QueuedJob | None]:
        return self._queue

    async def enqueue(self, payload: Dict[str, Any]) -> None:
        job = self._job_store.enqueue(payload)
        if self._running.is_set():
            await self._queue.put(job)
        else:
            await self._process_batch([job])

    async def _run(self) -> None:
        logger.info("MatchingWorker started")
        write_setting("worker.matching.last_start", datetime.utcnow().isoformat())
        record_worker_heartbeat("matching")
        pending = self._job_store.list_pending()
        for job in pending:
            await self._queue.put(job)

        self._worker_task = asyncio.create_task(self._worker_loop())

        try:
            await self._stop_event.wait()
        finally:
            await self._queue.put(None)
            if self._worker_task:
                await self._worker_task
            self._job_store.requeue_incomplete()
            self._running.clear()
            write_setting("worker.matching.last_stop", datetime.utcnow().isoformat())
            mark_worker_status("matching", WORKER_STOPPED)
            record_worker_stopped("matching")
            logger.info("MatchingWorker stopped")

    async def _worker_loop(self) -> None:
        while self._running.is_set():
            first_job = await self._queue.get()
            if first_job is None:
                break
            batch = [first_job]
            while len(batch) < self._batch_size:
                try:
                    job = await asyncio.wait_for(
                        self._queue.get(), timeout=self._batch_wait
                    )
                except asyncio.TimeoutError:
                    break
                if job is None:
                    await self._queue.put(None)
                    break
                batch.append(job)

            await self._process_batch(batch)
            for _ in batch:
                self._queue.task_done()

    async def _process_batch(self, jobs: List[QueuedJob]) -> None:
        stored_scores: List[float] = []
        discarded = 0

        for job in jobs:
            try:
                matches, rejected = await self._execute_job(job)
                discarded += rejected
                stored_scores.extend(score for _, score in matches)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Failed to process matching job %s: %s", job.id, exc)
                record_activity(
                    "metadata",
                    "matching_job_failed",
                    details={"job_id": job.id, "error": str(exc)},
                )

        average_confidence = statistics.mean(stored_scores) if stored_scores else 0.0
        write_setting(
            "metrics.matching.last_average_confidence",
            f"{average_confidence:.4f}",
        )
        write_setting("metrics.matching.last_discarded", str(discarded))
        increment_counter("metrics.matching.discarded_total", amount=discarded)
        increment_counter("metrics.matching.saved_total", amount=len(stored_scores))
        record_activity(
            "metadata",
            "matching_batch",
            details={
                "batch_size": len(jobs),
                "stored": len(stored_scores),
                "discarded": discarded,
                "average_confidence": round(average_confidence, 4),
            },
        )
        self._record_heartbeat()

    async def _execute_job(self, job: QueuedJob) -> Tuple[List[Tuple[Dict[str, Any], float]], int]:
        self._job_store.mark_running(job.id)
        payload = job.payload
        job_type = payload.get("type")
        spotify_track = payload.get("spotify_track")
        candidates = payload.get("candidates", [])
        if not spotify_track or not candidates:
            logger.warning("Invalid matching job received: %s", payload)
            self._job_store.mark_failed(job.id, "invalid_payload")
            return [], 0

        matches, discarded = self._evaluate_candidates(job_type, spotify_track, candidates)
        if matches:
            self._store_matches(job_type or "unknown", spotify_track, matches)
            self._job_store.mark_completed(job.id)
        else:
            self._job_store.mark_failed(job.id, "no_match")
        return matches, discarded

    def _evaluate_candidates(
        self, job_type: str | None, spotify_track: Dict[str, Any], candidates: Iterable[Dict[str, Any]]
    ) -> Tuple[List[Tuple[Dict[str, Any], float]], int]:
        matches: List[Tuple[Dict[str, Any], float]] = []
        rejected = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                rejected += 1
                continue
            if job_type == "spotify-to-plex":
                score = self._engine.calculate_match_confidence(spotify_track, candidate)
            else:
                score = self._engine.calculate_slskd_match_confidence(spotify_track, candidate)
            if score >= self._confidence_threshold:
                matches.append((candidate, score))
            else:
                rejected += 1
        matches.sort(key=lambda item: item[1], reverse=True)
        return matches, rejected

    def _store_matches(
        self,
        job_type: str,
        spotify_track: Dict[str, Any],
        matches: List[Tuple[Dict[str, Any], float]],
    ) -> None:
        with session_scope() as session:
            for candidate, score in matches:
                match = Match(
                    source=job_type,
                    spotify_track_id=str(spotify_track.get("id")),
                    target_id=str(candidate.get("id")) if candidate.get("id") else None,
                    confidence=score,
                )
                session.add(match)

    def _record_heartbeat(self) -> None:
        record_worker_heartbeat("matching")
