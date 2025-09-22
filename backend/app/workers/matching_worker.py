"""Asynchronous worker processing Spotify matching jobs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.utils.logging_config import get_logger
from backend.app.core.matching_engine import (
    MusicMatchingEngine,
    PlexTrackInfo,
    SoulseekTrackResult,
    SpotifyTrack,
)
from backend.app.core.spotify_client import SpotifyClient
from backend.app.models.matching_models import MatchHistory
from backend.app.models.plex_models import PlexAlbum, PlexArtist, PlexTrack


logger = get_logger("matching_worker")


@dataclass
class MatchingJob:
    job_type: Literal["spotify_to_plex", "spotify_to_soulseek"]
    spotify_track_id: str
    plex_artist_id: str | None = None
    soulseek_results: Iterable[SoulseekTrackResult] | None = None


class MatchingWorker:
    """Background worker for matching Spotify tracks against other services."""

    def __init__(
        self,
        spotify_client: SpotifyClient | None = None,
        engine: MusicMatchingEngine | None = None,
    ) -> None:
        self._spotify = spotify_client or SpotifyClient()
        self._engine = engine or MusicMatchingEngine()
        self._queue: asyncio.Queue[MatchingJob | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            logger.info("Matching worker started")

    async def stop(self) -> None:
        await self._queue.put(None)
        if self._task is not None:
            await self._task
            self._task = None
        logger.info("Matching worker stopped")

    async def enqueue_spotify_to_plex(self, spotify_track_id: str, plex_artist_id: str) -> None:
        job = MatchingJob("spotify_to_plex", spotify_track_id=spotify_track_id, plex_artist_id=plex_artist_id)
        await self._queue.put(job)
        logger.debug("Enqueued Spotify->Plex job for track %s", spotify_track_id)

    async def enqueue_spotify_to_soulseek(
        self, spotify_track_id: str, results: Iterable[SoulseekTrackResult]
    ) -> None:
        job = MatchingJob("spotify_to_soulseek", spotify_track_id=spotify_track_id, soulseek_results=list(results))
        await self._queue.put(job)
        logger.debug("Enqueued Spotify->Soulseek job for track %s", spotify_track_id)

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            try:
                if job.job_type == "spotify_to_plex":
                    self._process_spotify_to_plex(job.spotify_track_id, job.plex_artist_id)
                else:
                    results = list(job.soulseek_results or [])
                    self._process_spotify_to_soulseek(job.spotify_track_id, results)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Matching job %s failed: %s", job.job_type, exc)
            finally:
                self._queue.task_done()

    def _process_spotify_to_plex(self, spotify_track_id: str, plex_artist_id: str | None) -> None:
        if plex_artist_id is None:
            logger.error("Missing Plex artist id for Spotify match job")
            return

        spotify_track = self._load_spotify_track(spotify_track_id)
        with SessionLocal() as session:
            artist = session.get(PlexArtist, plex_artist_id)
            if artist is None:
                logger.warning("Plex artist %s not found", plex_artist_id)
                return

            tracks = (
                session.query(PlexTrack, PlexAlbum)
                .join(PlexAlbum, PlexTrack.album_id == PlexAlbum.id)
                .filter(PlexAlbum.artist_id == plex_artist_id)
                .all()
            )

            plex_tracks = [
                PlexTrackInfo(
                    id=track.id,
                    title=track.title,
                    artist=artist.name,
                    album=album.title,
                    duration_ms=track.duration,
                )
                for track, album in tracks
            ]

            if not plex_tracks:
                logger.info("No Plex tracks available for artist %s", plex_artist_id)
                return

            result = self._engine.find_best_match(spotify_track, plex_tracks)
            best_track: Optional[PlexTrackInfo] = result.get("track")  # type: ignore[assignment]
            confidence = float(result.get("confidence", 0.0))
            matched = bool(result.get("matched")) and best_track is not None

            if matched and best_track is not None:
                self._store_history(session, "plex", spotify_track.id, best_track.id, confidence)
                logger.info(
                    "Matched Spotify track %s to Plex track %s with confidence %.3f",
                    spotify_track.id,
                    best_track.id,
                    confidence,
                )

    def _process_spotify_to_soulseek(self, spotify_track_id: str, results: Iterable[SoulseekTrackResult]) -> None:
        spotify_track = self._load_spotify_track(spotify_track_id)
        best_result: Optional[SoulseekTrackResult] = None
        best_confidence = 0.0
        for candidate in results:
            confidence = self._engine.calculate_slskd_match_confidence(spotify_track, candidate)
            if confidence > best_confidence:
                best_confidence = confidence
                best_result = candidate

        if best_result is None:
            logger.info("No Soulseek match found for Spotify track %s", spotify_track.id)
            return

        with SessionLocal() as session:
            target_id = best_result.id or best_result.filename
            self._store_history(session, "soulseek", spotify_track.id, target_id, best_confidence)
            logger.info(
                "Matched Spotify track %s to Soulseek result %s with confidence %.3f",
                spotify_track.id,
                target_id,
                best_confidence,
            )

    def _load_spotify_track(self, spotify_track_id: str) -> SpotifyTrack:
        data = self._spotify.get_track_details(spotify_track_id)
        album = data.get("album") or {}
        if not isinstance(album, dict):
            album = {}
        return SpotifyTrack(
            id=data.get("id", spotify_track_id),
            name=data.get("name", ""),
            artists=list(data.get("artists", [])),
            album=album.get("name"),
            duration_ms=data.get("duration_ms"),
        )

    def _store_history(self, session: Session, source: str, spotify_track_id: str, target_id: str, confidence: float) -> None:
        history = MatchHistory(
            source=source,
            spotify_track_id=spotify_track_id,
            target_id=target_id,
            confidence=confidence,
        )
        session.add(history)
        session.commit()


__all__ = ["MatchingWorker", "MatchingJob"]

