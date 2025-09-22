"""Background worker handling deferred matching operations."""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.core.matching_engine import MusicMatchingEngine
from app.db import SessionLocal
from app.logging import get_logger
from app.models import Match

logger = get_logger(__name__)


class MatchingWorker:
    def __init__(self, engine: MusicMatchingEngine) -> None:
        self._engine = engine
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running = asyncio.Event()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._running.set()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running.clear()
        if self._task:
            await self._queue.put({"_shutdown": True})
            await self._task

    @property
    def queue(self) -> asyncio.Queue[Dict[str, Any]]:
        return self._queue

    async def _run(self) -> None:
        logger.info("MatchingWorker started")
        while self._running.is_set():
            job = await self._queue.get()
            try:
                if job.get("_shutdown"):
                    break
                await self._process_job(job)
            except Exception as exc:  # pragma: no cover
                logger.error("Failed to process matching job: %s", exc)
            finally:
                self._queue.task_done()
        logger.info("MatchingWorker stopped")

    async def _process_job(self, job: Dict[str, Any]) -> None:
        job_type = job.get("type")
        spotify_track = job.get("spotify_track")
        candidates = job.get("candidates", [])
        if not spotify_track or not candidates:
            logger.warning("Invalid matching job received: %s", job)
            return
        if job_type == "spotify-to-plex":
            best_match, confidence = self._engine.find_best_match(spotify_track, candidates)
        else:
            best_match = None
            confidence = 0.0
            for candidate in candidates:
                score = self._engine.calculate_slskd_match_confidence(spotify_track, candidate)
                if score > confidence:
                    confidence = score
                    best_match = candidate
        self._store_match(job_type, spotify_track, best_match, confidence)

    def _store_match(
        self,
        job_type: str,
        spotify_track: Dict[str, Any],
        best_match: Dict[str, Any] | None,
        confidence: float,
    ) -> None:
        session: Session = SessionLocal()
        try:
            match = Match(
                source=job_type,
                spotify_track_id=str(spotify_track.get("id")),
                target_id=str(best_match.get("id")) if best_match and best_match.get("id") else None,
                confidence=confidence,
            )
            session.add(match)
            session.commit()
        finally:
            session.close()
