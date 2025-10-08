"""Service layer for Spotify FREE ingest submissions."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import (TYPE_CHECKING, Any, Awaitable, Callable, Dict, Iterable,
                    List, Optional, Sequence, Tuple)
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.config import AppConfig
from app.core.soulseek_client import SoulseekClient
from app.db import SessionCallable, run_session, session_scope
from app.logging import get_logger
from app.logging_events import log_event
from app.models import (Download, IngestItem, IngestItemState, IngestJob,
                        IngestJobState)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.workers.sync_worker import SyncWorker


logger = get_logger(__name__)

LOSSLESS_FORMATS: set[str] = {"flac", "alac", "ape", "wav"}
_DURATION_PATTERN = re.compile(r"(?:(?P<hours>\d+):)?(?P<minutes>\d{1,2}):(?P<seconds>\d{2})")
_DASH_PATTERN = re.compile(r"\s*[-–—]\s*")


@dataclass(slots=True)
class InvalidPlaylistLink:
    url: str
    reason: str


class PlaylistValidationError(ValueError):
    """Raised when playlist URLs fail validation."""

    def __init__(self, invalid_links: Sequence[InvalidPlaylistLink]) -> None:
        self.invalid_links = list(invalid_links)
        message = ", ".join(f"{item.url}:{item.reason}" for item in self.invalid_links)
        super().__init__(message or "invalid playlist links")


@dataclass(slots=True)
class NormalizedTrack:
    item_id: int
    artist: str
    title: str
    album: Optional[str]
    duration_sec: Optional[int]
    raw_line: str


@dataclass(slots=True)
class IngestAccepted:
    playlists: int
    tracks: int
    batches: int


@dataclass(slots=True)
class IngestSkipped:
    playlists: int
    tracks: int
    reason: Optional[str] = None


@dataclass(slots=True)
class IngestSubmission:
    ok: bool
    job_id: str
    accepted: IngestAccepted
    skipped: IngestSkipped
    error: Optional[str]


@dataclass(slots=True)
class JobCounts:
    registered: int
    normalized: int
    queued: int
    completed: int
    failed: int


@dataclass(slots=True)
class JobStatus:
    id: str
    state: str
    counts: JobCounts
    accepted: IngestAccepted
    skipped: IngestSkipped
    error: Optional[str]
    queued_tracks: int
    failed_tracks: int
    skipped_tracks: int
    skip_reason: Optional[str]


@dataclass(slots=True)
class PlaylistEnqueueResult:
    """Outcome returned when enqueueing playlist identifiers."""

    accepted_ids: list[str]
    duplicate_ids: list[str]
    error: Optional[str] = None
    job_id: Optional[str] = None


SessionRunner = Callable[[SessionCallable[Any]], Awaitable[Any]]


class FreeIngestService:
    """Coordinate ingestion of playlist links and track lists for FREE mode."""

    def __init__(
        self,
        *,
        config: AppConfig,
        soulseek_client: SoulseekClient,
        sync_worker: "SyncWorker | None",
        session_runner: "SessionRunner | None" = None,
    ) -> None:
        self._config = config
        self._soulseek = soulseek_client
        self._sync_worker = sync_worker
        self._run_session: SessionRunner = session_runner or run_session

    async def submit(
        self,
        *,
        playlist_links: Sequence[str] | None = None,
        tracks: Sequence[str] | None = None,
        batch_hint: Optional[int] = None,
    ) -> IngestSubmission:
        playlist_links = playlist_links or []
        tracks = tracks or []

        normalised_links, skipped_playlists, playlist_skip_reason = self._normalise_playlists(
            playlist_links
        )
        normalised_tracks, skipped_tracks, track_skip_reason = self._normalise_tracks(tracks)

        skip_reason = playlist_skip_reason or track_skip_reason
        job_id = f"job_{uuid.uuid4().hex}"
        batch_size = self._resolve_batch_size(batch_hint)
        initial_tracks = len(normalised_tracks)

        logger.info(
            "event=ingest_normalized source=FREE job_id=%s playlists=%s tracks=%s",
            job_id,
            len(normalised_links),
            initial_tracks,
        )

        accepted_playlists = list(normalised_links)
        accepted_tracks = list(normalised_tracks)
        job_error: Optional[str] = None

        has_capacity = await self._has_capacity()
        if not has_capacity and (accepted_playlists or accepted_tracks):
            job_error = "backpressure"
            skip_reason = skip_reason or job_error
            skipped_playlists += len(accepted_playlists)
            skipped_tracks += len(accepted_tracks)
            accepted_playlists.clear()
            accepted_tracks.clear()
            logger.warning(
                "event=ingest_skipped source=FREE job_id=%s reason=%s pending_limit=%s",
                job_id,
                job_error,
                self._config.ingest.max_pending_jobs,
            )
        elif skip_reason:
            logger.info(
                "event=ingest_skipped source=FREE job_id=%s reason=%s skipped_playlists=%s skipped_tracks=%s",
                job_id,
                skip_reason,
                skipped_playlists,
                skipped_tracks,
            )

        job_note = job_error or skip_reason

        await self._persist_job(
            job_id=job_id,
            playlists=accepted_playlists,
            tracks=accepted_tracks,
            skipped_playlists=skipped_playlists,
            skipped_tracks=skipped_tracks,
        )

        total_tracks = len(accepted_tracks)
        queued_tracks = 0
        failed_tracks = 0

        if accepted_tracks:
            try:
                queued_tracks, failed_tracks = await self._enqueue_tracks(
                    job_id,
                    accepted_tracks,
                    batch_size=batch_size,
                )
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.error("event=ingest_enqueue_failed job_id=%s error=%s", job_id, exc)
                await self._update_job_state(job_id, IngestJobState.FAILED, error=str(exc))
                raise
        else:
            await self._update_job_state(
                job_id,
                IngestJobState.NORMALIZED,
                error=job_note,
            )

        await self._finalise_job_state(
            job_id,
            total_tracks=total_tracks,
            queued_tracks=queued_tracks,
            failed_tracks=failed_tracks,
            skipped_tracks=skipped_tracks,
            skip_reason=skip_reason,
            error=job_note,
        )

        accepted = IngestAccepted(
            playlists=len(accepted_playlists),
            tracks=total_tracks,
            batches=self._calculate_batches(total_tracks, batch_size),
        )
        skipped = IngestSkipped(
            playlists=skipped_playlists,
            tracks=skipped_tracks,
            reason=skip_reason,
        )

        submission_error = job_error
        if submission_error is None and failed_tracks and queued_tracks:
            submission_error = "partial"

        return IngestSubmission(
            ok=True,
            job_id=job_id,
            accepted=accepted,
            skipped=skipped,
            error=submission_error,
        )

    async def enqueue_playlists(
        self, playlist_ids: Sequence[str]
    ) -> PlaylistEnqueueResult:
        """Enqueue playlist identifiers via the FREE ingest pipeline."""

        unique_ids: list[str] = []
        seen: set[str] = set()
        for raw in playlist_ids:
            candidate = (raw or "").strip()
            if not candidate:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            unique_ids.append(candidate)

        if not unique_ids:
            return PlaylistEnqueueResult(accepted_ids=[], duplicate_ids=[])

        hashed_ids: list[tuple[str, str]] = [
            (playlist_id, self._hash_parts(playlist_id)) for playlist_id in unique_ids
        ]
        digests = [digest for _, digest in hashed_ids]

        def _load_existing(session) -> set[str]:
            rows = (
                session.execute(
                    select(IngestItem.dedupe_hash)
                    .where(IngestItem.dedupe_hash.in_(digests))
                    .where(
                        IngestItem.state.in_(
                            [
                                IngestItemState.REGISTERED.value,
                                IngestItemState.NORMALIZED.value,
                                IngestItemState.QUEUED.value,
                            ]
                        )
                    )
                )
                .scalars()
                .all()
            )
            return set(rows)

        existing_hashes = await self._run_session(_load_existing)

        duplicate_ids = [
            playlist_id for playlist_id, digest in hashed_ids if digest in existing_hashes
        ]
        pending_ids = [
            playlist_id for playlist_id, digest in hashed_ids if digest not in existing_hashes
        ]

        if not pending_ids:
            return PlaylistEnqueueResult(accepted_ids=[], duplicate_ids=duplicate_ids)

        canonical_links = [
            f"https://open.spotify.com/playlist/{playlist_id}" for playlist_id in pending_ids
        ]
        submission = await self.submit(playlist_links=canonical_links)

        accepted_count = min(len(pending_ids), submission.accepted.playlists)
        accepted_ids = pending_ids[:accepted_count]
        skipped_ids = pending_ids[accepted_count:]

        status_label = "enqueued" if accepted_count else "skipped"
        payload: dict[str, Any] = {
            "component": "service.free_ingest",
            "entity_id": submission.job_id,
            "job_type": "spotify_free_links",
            "status": status_label,
            "attempts": 1,
            "accepted": submission.accepted.playlists,
            "skipped": submission.skipped.playlists,
        }
        if submission.error:
            payload["error"] = submission.error
        log_event(
            logger,
            "worker.job",
            meta={"playlist_ids": pending_ids, "accepted": accepted_count},
            **payload,
        )

        duplicate_ids.extend(skipped_ids)

        return PlaylistEnqueueResult(
            accepted_ids=accepted_ids,
            duplicate_ids=duplicate_ids,
            error=submission.error,
            job_id=submission.job_id,
        )

    def get_job_status(self, job_id: str) -> JobStatus | None:
        with session_scope() as session:
            job = session.get(IngestJob, job_id)
            if job is None:
                return None

            counts_raw = (
                session.execute(
                    select(IngestItem.state, func.count())
                    .where(IngestItem.job_id == job_id)
                    .group_by(IngestItem.state)
                )
                .tuples()
                .all()
            )

            counts_map = {state: total for state, total in counts_raw}
            counts = JobCounts(
                registered=int(counts_map.get("registered", 0)),
                normalized=int(counts_map.get("normalized", 0)),
                queued=int(counts_map.get("queued", 0)),
                completed=int(counts_map.get("completed", 0)),
                failed=int(counts_map.get("failed", 0)),
            )

            playlist_total = session.execute(
                select(func.count())
                .select_from(IngestItem)
                .where(
                    IngestItem.job_id == job_id,
                    IngestItem.source_type == "LINK",
                )
            ).scalar_one()
            track_total = session.execute(
                select(func.count())
                .select_from(IngestItem)
                .where(
                    IngestItem.job_id == job_id,
                    IngestItem.source_type != "LINK",
                )
            ).scalar_one()

            batches = self._calculate_batches(int(track_total), self._resolve_batch_size(None))
            accepted = IngestAccepted(
                playlists=int(playlist_total),
                tracks=int(track_total),
                batches=batches,
            )
            skipped_tracks_total = int(job.skipped_tracks or 0)
            skip_reason = None
            stored_error = job.error
            error_message, skip_reason = self._split_error_and_skip_reason(job.state, stored_error)
            skipped = IngestSkipped(
                playlists=int(job.skipped_playlists or 0),
                tracks=skipped_tracks_total,
                reason=skip_reason,
            )

            queued_tracks = int(counts.queued + counts.completed)
            failed_tracks = counts.failed

            return JobStatus(
                id=job.id,
                state=job.state,
                counts=counts,
                accepted=accepted,
                skipped=skipped,
                error=error_message,
                queued_tracks=queued_tracks,
                failed_tracks=failed_tracks,
                skipped_tracks=skipped_tracks_total,
                skip_reason=skip_reason,
            )

    # Playlist helpers -----------------------------------------------------

    def _normalise_playlists(
        self, playlist_links: Sequence[str]
    ) -> Tuple[List[Tuple[str, str]], int, Optional[str]]:
        max_playlists = self._config.free_ingest.max_playlists
        accepted: List[Tuple[str, str]] = []
        invalid: List[InvalidPlaylistLink] = []
        seen_ids: set[str] = set()
        skipped = 0
        skip_reason: Optional[str] = None

        for raw in playlist_links:
            text = (raw or "").strip()
            if not text:
                invalid.append(InvalidPlaylistLink(url=raw, reason="EMPTY"))
                continue
            try:
                normalised, playlist_id = self._validate_playlist_link(text)
            except ValueError as exc:
                invalid.append(InvalidPlaylistLink(url=text, reason=str(exc)))
                continue

            if playlist_id in seen_ids:
                skipped += 1
                skip_reason = skip_reason or "duplicate"
                continue

            if len(accepted) >= max_playlists:
                skipped += 1
                skip_reason = "limit"
                continue

            accepted.append((normalised, playlist_id))
            seen_ids.add(playlist_id)

        if invalid:
            raise PlaylistValidationError(invalid)

        return accepted, skipped, skip_reason

    @staticmethod
    def _validate_playlist_link(url: str) -> Tuple[str, str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("INVALID_SCHEME")
        if parsed.netloc.lower() != "open.spotify.com":
            raise ValueError("UNSUPPORTED_HOST")
        segments = [segment for segment in parsed.path.split("/") if segment]
        if segments and segments[0].lower().startswith("intl-"):
            segments = segments[1:]
        if not segments or segments[0].lower() != "playlist":
            raise ValueError("NOT_A_PLAYLIST")
        if len(segments) < 2:
            raise ValueError("INVALID_PLAYLIST_ID")
        playlist_id = segments[1].split("?")[0].split("#")[0]
        if not playlist_id.isalnum():
            raise ValueError("INVALID_PLAYLIST_ID")
        canonical = f"https://open.spotify.com/playlist/{playlist_id}"
        return canonical, playlist_id

    # Track helpers --------------------------------------------------------

    def _normalise_tracks(
        self, tracks: Sequence[str]
    ) -> Tuple[List[NormalizedTrack], int, Optional[str]]:
        if not tracks:
            return [], 0, None

        max_tracks = self._config.free_ingest.max_tracks
        accepted: List[NormalizedTrack] = []
        skipped = 0
        skip_reason: Optional[str] = None
        seen_hashes: set[str] = set()
        limited_tracks = list(tracks[:max_tracks])

        if len(tracks) > max_tracks:
            skipped += len(tracks) - max_tracks
            skip_reason = "limit"

        for raw in limited_tracks:
            text = (raw or "").strip()
            if not text:
                skipped += 1
                skip_reason = skip_reason or "invalid"
                continue
            parsed = self._parse_track_line(text)
            if parsed is None:
                skipped += 1
                skip_reason = skip_reason or "invalid"
                continue

            artist, title, album, duration_sec = parsed
            dedupe_hash = self._hash_parts(artist, title, album or "", duration_sec or "")
            if dedupe_hash in seen_hashes:
                skipped += 1
                skip_reason = skip_reason or "duplicate"
                continue
            seen_hashes.add(dedupe_hash)
            accepted.append(
                NormalizedTrack(
                    item_id=0,
                    artist=artist,
                    title=title,
                    album=album,
                    duration_sec=duration_sec,
                    raw_line=text,
                )
            )

        return accepted, skipped, skip_reason

    def _parse_track_line(self, line: str) -> Tuple[str, str, Optional[str], Optional[int]] | None:
        duration = self._extract_duration(line)
        cleaned = line
        if duration is not None:
            cleaned = _DURATION_PATTERN.sub("", cleaned).strip()

        album = None
        album_match = re.search(r"\(([^()]+)\)\s*$", cleaned)
        if album_match:
            album_candidate = album_match.group(1).strip()
            if album_candidate:
                album = album_candidate
                cleaned = cleaned[: album_match.start()].strip()

        parts = _DASH_PATTERN.split(cleaned, maxsplit=1)
        if len(parts) < 2:
            return None

        artist = parts[0].strip()
        title = parts[1].strip()
        if not artist or not title:
            return None

        return artist, title, album, duration

    @staticmethod
    def _extract_duration(text: str) -> Optional[int]:
        match = _DURATION_PATTERN.search(text)
        if not match:
            return None
        hours = int(match.group("hours") or 0)
        minutes = int(match.group("minutes") or 0)
        seconds = int(match.group("seconds") or 0)
        total_seconds = (hours * 3600) + (minutes * 60) + seconds
        if total_seconds <= 0:
            return None
        return total_seconds

    @staticmethod
    def _hash_parts(*parts: Any) -> str:
        digest = hashlib.sha1()
        for part in parts:
            digest.update(str(part).strip().lower().encode("utf-8"))
            digest.update(b"::")
        return digest.hexdigest()

    # Persistence helpers --------------------------------------------------

    async def _has_capacity(self) -> bool:
        def _query(session) -> int:
            pending = session.execute(
                select(func.count())
                .select_from(IngestJob)
                .where(
                    IngestJob.state.in_(
                        [
                            IngestJobState.REGISTERED.value,
                            IngestJobState.NORMALIZED.value,
                            IngestJobState.QUEUED.value,
                        ]
                    )
                )
            ).scalar_one()
            return int(pending)

        pending_jobs = await self._run_session(_query)
        return pending_jobs < self._config.ingest.max_pending_jobs

    async def _persist_job(
        self,
        *,
        job_id: str,
        playlists: Sequence[Tuple[str, str]],
        tracks: Sequence[NormalizedTrack],
        skipped_playlists: int,
        skipped_tracks: int,
    ) -> None:
        now = datetime.utcnow()

        def _persist(session) -> None:
            job = IngestJob(
                id=job_id,
                source="FREE",
                created_at=now,
                state=IngestJobState.REGISTERED.value,
                skipped_playlists=skipped_playlists,
                skipped_tracks=skipped_tracks,
                error=None,
            )
            session.add(job)
            session.flush()

            for url, playlist_id in playlists:
                fingerprint = self._hash_parts(url)
                item = IngestItem(
                    job_id=job_id,
                    source_type="LINK",
                    playlist_url=url,
                    raw_line=None,
                    artist=None,
                    title=None,
                    album=None,
                    duration_sec=None,
                    dedupe_hash=self._hash_parts(playlist_id),
                    source_fingerprint=fingerprint,
                    state=IngestItemState.REGISTERED.value,
                    error=None,
                    created_at=now,
                )
                session.add(item)
                session.flush()
                item.state = IngestItemState.NORMALIZED.value
                session.add(item)

            for track in tracks:
                fingerprint = self._hash_parts(track.raw_line)
                item = IngestItem(
                    job_id=job_id,
                    source_type="FILE",
                    playlist_url=None,
                    raw_line=track.raw_line,
                    artist=track.artist,
                    title=track.title,
                    album=track.album,
                    duration_sec=track.duration_sec,
                    dedupe_hash=self._hash_parts(
                        track.artist,
                        track.title,
                        track.album or "",
                        track.duration_sec or "",
                    ),
                    source_fingerprint=fingerprint,
                    state=IngestItemState.REGISTERED.value,
                    error=None,
                    created_at=now,
                )
                session.add(item)
                session.flush()
                item.state = IngestItemState.NORMALIZED.value
                session.add(item)
                track.item_id = item.id

            job.state = IngestJobState.NORMALIZED.value
            session.add(job)

        await self._run_session(_persist)

    async def _update_job_state(
        self,
        job_id: str,
        state: IngestJobState | str,
        *,
        error: str | None = None,
    ) -> None:
        def _update(session) -> None:
            job = session.get(IngestJob, job_id)
            if job is None:
                return
            job.state = state.value if isinstance(state, IngestJobState) else str(state)
            job.error = error
            session.add(job)

        await self._run_session(_update)

    async def _finalise_job_state(
        self,
        job_id: str,
        *,
        total_tracks: int,
        queued_tracks: int,
        failed_tracks: int,
        skipped_tracks: int,
        skip_reason: str | None,
        error: str | None,
    ) -> None:
        if total_tracks == 0:
            final_state = IngestJobState.COMPLETED
            final_error = error
        elif queued_tracks == total_tracks:
            final_state = IngestJobState.COMPLETED
            final_error = error
        elif queued_tracks > 0:
            final_state = IngestJobState.COMPLETED
            final_error = f"partial queued={queued_tracks} failed={failed_tracks}"
        else:
            final_state = IngestJobState.FAILED
            final_error = error or f"failed={failed_tracks}"

        stored_error = final_error
        if skip_reason and final_error and skip_reason != final_error:
            stored_error = f"{final_error}||skip_reason={skip_reason}"
        elif skip_reason and not final_error:
            stored_error = skip_reason

        await self._update_job_state(job_id, final_state, error=stored_error)
        logger.info(
            "event=ingest_completed source=FREE job_id=%s state=%s queued=%s failed=%s skipped=%s skip_reason=%s",
            job_id,
            final_state.value,
            queued_tracks,
            failed_tracks,
            skipped_tracks,
            skip_reason,
        )

    @staticmethod
    def _split_error_and_skip_reason(
        job_state: str, stored_error: str | None
    ) -> tuple[Optional[str], Optional[str]]:
        if stored_error is None:
            return None, None

        text = stored_error.strip()
        if not text:
            return None, None

        skip_reason: Optional[str] = None
        message: Optional[str] = text

        if "||skip_reason=" in text:
            base, _, skip = text.partition("||skip_reason=")
            message = base.strip() or None
            skip = skip.strip()
            skip_reason = skip or None
        else:
            if job_state != IngestJobState.FAILED.value and not text.startswith("partial "):
                skip_reason = text

        return message, skip_reason

    # Queue helpers --------------------------------------------------------

    async def _enqueue_tracks(
        self,
        job_id: str,
        tracks: Sequence[NormalizedTrack],
        *,
        batch_size: int,
    ) -> Tuple[int, int]:
        if not tracks:
            return 0, 0

        await self._update_job_state(job_id, IngestJobState.QUEUED)
        queued = 0
        failed = 0

        for batch in self._chunk(tracks, batch_size):
            for track in batch:
                try:
                    success = await self._enqueue_track(job_id, track)
                except Exception as exc:
                    logger.error(
                        "event=ingest_enqueue_failed job_id=%s item_id=%s error=%s",
                        job_id,
                        track.item_id,
                        exc,
                    )
                    await self._set_item_state(
                        track.item_id,
                        IngestItemState.FAILED,
                        error=str(exc),
                    )
                    failed += 1
                    continue
                if success:
                    queued += 1
                else:
                    failed += 1

        logger.info(
            "event=ingest_enqueued source=FREE job_id=%s queued=%s failed=%s batches=%s",
            job_id,
            queued,
            failed,
            self._calculate_batches(len(tracks), batch_size),
        )
        return queued, failed

    async def _enqueue_track(self, job_id: str, track: NormalizedTrack) -> bool:
        queries = self._generate_search_queries(track)
        username: Optional[str] = None
        candidate: Optional[Dict[str, Any]] = None
        query_used: Optional[str] = None

        for query in queries:
            if not query:
                continue
            try:
                results = await self._soulseek.search(
                    query,
                    format_priority=tuple(LOSSLESS_FORMATS),
                )
            except Exception:
                raise
            username, candidate = self._select_candidate(results)
            if username and candidate:
                query_used = query
                break

        if not username or not candidate or not query_used:
            await self._set_item_state(track.item_id, IngestItemState.FAILED, error="no_match")
            return False

        priority = 10 if str(candidate.get("format", "")).lower() in LOSSLESS_FORMATS else 0
        download_id = await self._create_download_record(
            job_id=job_id,
            track=track,
            username=username,
            file_info=candidate,
            priority=priority,
            query=query_used,
        )

        job_file = dict(candidate)
        job_file.setdefault("filename", job_file.get("name"))
        job_file["download_id"] = download_id
        job_file["priority"] = priority
        job_payload = {"username": username, "files": [job_file]}

        try:
            if self._sync_worker is not None:
                await self._sync_worker.enqueue(job_payload)
            else:
                await self._soulseek.download(job_payload)
        except Exception:
            await self._set_item_state(track.item_id, IngestItemState.FAILED, error="queue_error")
            raise

        await self._set_item_state(track.item_id, IngestItemState.QUEUED, error=None)
        return True

    async def _create_download_record(
        self,
        *,
        job_id: str,
        track: NormalizedTrack,
        username: str,
        file_info: Dict[str, Any],
        priority: int,
        query: str,
    ) -> int:
        def _create(session) -> int:
            download = Download(
                filename=file_info.get("filename")
                or file_info.get("name")
                or f"{track.title}.flac",
                state="queued",
                progress=0.0,
                username=username,
                priority=priority,
            )
            session.add(download)
            session.flush()
            payload = {
                "source": "free_ingest",
                "job_id": job_id,
                "ingest_item_id": track.item_id,
                "query": query,
                "track": {
                    "artist": track.artist,
                    "title": track.title,
                    "album": track.album,
                    "duration_sec": track.duration_sec,
                },
                "file": dict(file_info),
            }
            payload["download_id"] = download.id
            payload["priority"] = priority
            download.request_payload = payload
            download.job_id = job_id
            session.add(download)
            return download.id

        return await self._run_session(_create)

    @staticmethod
    def _generate_search_queries(track: NormalizedTrack) -> List[str]:
        queries: List[str] = []
        parts = [track.title, track.artist, track.album]
        primary = " ".join(part for part in parts if part)
        if primary:
            queries.append(primary)

        title_artist = " ".join(part for part in [track.title, track.artist] if part)
        if title_artist and title_artist not in queries:
            queries.append(title_artist)

        artist_title = " ".join(part for part in [track.artist, track.title] if part)
        if artist_title and artist_title not in queries:
            queries.append(artist_title)

        if track.title and track.title not in queries:
            queries.append(track.title)

        return queries

    @staticmethod
    def _select_candidate(payload: Any) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
        if not isinstance(payload, dict):
            return None, None
        candidates = payload.get("results")
        if not isinstance(candidates, list):
            candidates = []
        best: tuple[int, int, int, str, Dict[str, Any]] | None = None
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            username = entry.get("username") or entry.get("user")
            files = entry.get("files")
            if not username or not isinstance(files, Iterable):
                continue
            for file_info in files:
                if not isinstance(file_info, dict):
                    continue
                candidate = dict(file_info)
                filename = (
                    candidate.get("filename")
                    or candidate.get("name")
                    or candidate.get("title")
                    or candidate.get("path")
                )
                if filename:
                    candidate["filename"] = str(filename)
                format_name = str(
                    candidate.get("format") or candidate.get("extension") or ""
                ).lower()
                if not format_name and isinstance(candidate.get("filename"), str):
                    filename = str(candidate["filename"])
                    if "." in filename:
                        format_name = filename.rsplit(".", 1)[-1].lower()
                lossless = 1 if format_name in LOSSLESS_FORMATS else 0
                try:
                    bitrate = int(candidate.get("bitrate") or 0)
                except (TypeError, ValueError):
                    bitrate = 0
                try:
                    size = int(candidate.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                score = (lossless, bitrate, size)
                if best is None or score > best[:3]:
                    best = (*score, str(username), candidate)
        if best is None:
            return None, None
        _, _, _, username, candidate = best
        return username, candidate

    async def _set_item_state(
        self,
        item_id: int,
        state: IngestItemState | str,
        *,
        error: str | None,
    ) -> None:
        def _update(session) -> None:
            item = session.get(IngestItem, item_id)
            if item is None:
                return
            item.state = state.value if isinstance(state, IngestItemState) else str(state)
            item.error = error
            session.add(item)

        await self._run_session(_update)

    @staticmethod
    def _chunk(items: Sequence[NormalizedTrack], size: int) -> Iterable[Sequence[NormalizedTrack]]:
        if size <= 0:
            size = 1
        for start in range(0, len(items), size):
            yield items[start : start + size]

    def _resolve_batch_size(self, batch_hint: Optional[int]) -> int:
        base = max(1, self._config.ingest.batch_size)
        ceiling = max(base, self._config.free_ingest.batch_size)
        if batch_hint is None:
            return ceiling
        return max(1, min(batch_hint, ceiling * 2))

    @staticmethod
    def _calculate_batches(total_tracks: int, batch_size: int) -> int:
        if total_tracks <= 0:
            return 0
        size = max(1, batch_size)
        return math.ceil(total_tracks / size)

    # Parsing utilities ----------------------------------------------------

    @staticmethod
    def parse_tracks_from_file(content: bytes, filename: str) -> List[str]:
        suffix = filename.lower().rsplit(".", 1)
        extension = suffix[-1] if len(suffix) == 2 else ""
        text = content.decode("utf-8", errors="ignore")

        if extension == "json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError("INVALID_JSON") from None
            if isinstance(payload, dict):
                tracks = payload.get("tracks")
            else:
                tracks = payload
            if not isinstance(tracks, list):
                raise ValueError("INVALID_JSON_STRUCTURE")
            return [str(item) for item in tracks]

        if extension == "csv":
            reader = csv.reader(StringIO(text))
            return [cell.strip() for row in reader for cell in row if str(cell).strip()]

        return [line.strip() for line in text.replace("\r", "").split("\n") if line.strip()]
