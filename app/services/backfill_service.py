"""Spotify backfill service coordinating track enrichment and playlist expansion."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import Select, func, select

from app.config import SpotifyConfig
from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.logging import get_logger
from app.models import BackfillJob, IngestItem, IngestItemState, SpotifyCache

logger = get_logger(__name__)


@dataclass(slots=True)
class CandidateItem:
    """Normalized representation of an ingest item awaiting Spotify enrichment."""

    id: int
    artist: str
    title: str
    album: Optional[str]
    duration_ms: Optional[int]


@dataclass(slots=True)
class PlaylistLink:
    """Container for playlist entries discovered during ingest."""

    item_id: int
    job_id: str
    url: str


@dataclass(slots=True)
class BackfillJobSpec:
    """Descriptor returned when a new backfill job is created."""

    id: str
    limit: int
    expand_playlists: bool


@dataclass(slots=True)
class BackfillJobStatus:
    """External representation of a persisted backfill job."""

    id: str
    state: str
    requested_items: int
    processed_items: int
    matched_items: int
    cache_hits: int
    cache_misses: int
    expanded_playlists: int
    expanded_tracks: int
    expand_playlists: bool
    duration_ms: Optional[int]
    error: Optional[str]


class BackfillService:
    """Orchestrate Spotify enrichment for FREE ingest items."""

    def __init__(self, config: SpotifyConfig, spotify_client: SpotifyClient) -> None:
        self._config = config
        self._spotify = spotify_client
        self._default_limit = max(1, getattr(config, "backfill_max_items", 2_000))
        self._cache_ttl = max(60, getattr(config, "backfill_cache_ttl_seconds", 604_800))

    # Public API ---------------------------------------------------------

    def create_job(self, *, max_items: Optional[int], expand_playlists: bool) -> BackfillJobSpec:
        """Persist a new job entry that will later be executed by the worker."""

        self._ensure_authenticated()

        limit = self._resolve_limit(max_items)
        available = self._count_candidates()
        requested = min(limit, available)

        job_id = f"backfill_{uuid.uuid4().hex}"
        now = datetime.utcnow()

        with session_scope() as session:
            job = BackfillJob(
                id=job_id,
                state="queued",
                requested_items=requested,
                processed_items=0,
                matched_items=0,
                cache_hits=0,
                cache_misses=0,
                expanded_playlists=0,
                expanded_tracks=0,
                expand_playlists=expand_playlists,
                error=None,
                duration_ms=None,
                created_at=now,
            )
            session.add(job)

        return BackfillJobSpec(id=job_id, limit=limit, expand_playlists=expand_playlists)

    async def execute(self, job: BackfillJobSpec) -> None:
        """Run a backfill job asynchronously inside a worker thread."""

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.run_job, job)

    def get_status(self, job_id: str) -> Optional[BackfillJobStatus]:
        """Return a snapshot of the persisted job state."""

        with session_scope() as session:
            record = session.get(BackfillJob, job_id)
            if record is None:
                return None

            return BackfillJobStatus(
                id=record.id,
                state=record.state,
                requested_items=int(record.requested_items or 0),
                processed_items=int(record.processed_items or 0),
                matched_items=int(record.matched_items or 0),
                cache_hits=int(record.cache_hits or 0),
                cache_misses=int(record.cache_misses or 0),
                expanded_playlists=int(record.expanded_playlists or 0),
                expanded_tracks=int(record.expanded_tracks or 0),
                expand_playlists=bool(record.expand_playlists),
                duration_ms=record.duration_ms,
                error=record.error,
            )

    # Core processing ----------------------------------------------------

    def run_job(self, job: BackfillJobSpec) -> None:
        start_time = time.perf_counter()
        processed = 0
        matched = 0
        cache_hits = 0
        cache_misses = 0
        playlists_expanded = 0
        tracks_added = 0
        metadata_cache: Dict[str, Dict[str, Any]] = {}

        logger.info(
            "event=backfill job_id=%s state=running limit=%s expand_playlists=%s",
            job.id,
            job.limit,
            job.expand_playlists,
        )

        self._update_job_state(job.id, state="running", error=None)

        try:
            candidates = self._load_candidates(job.limit)
            for candidate in candidates:
                processed += 1
                matched_item, from_cache = self._process_candidate(candidate, metadata_cache)
                if from_cache:
                    cache_hits += 1
                else:
                    cache_misses += 1
                if matched_item:
                    matched += 1

                self._persist_progress(
                    job.id,
                    processed=processed,
                    matched=matched,
                    cache_hits=cache_hits,
                    cache_misses=cache_misses,
                    expanded_playlists=playlists_expanded,
                    expanded_tracks=tracks_added,
                )

            if job.expand_playlists:
                playlists_expanded, tracks_added = self._expand_playlists(job.id)
                self._persist_progress(
                    job.id,
                    processed=processed,
                    matched=matched,
                    cache_hits=cache_hits,
                    cache_misses=cache_misses,
                    expanded_playlists=playlists_expanded,
                    expanded_tracks=tracks_added,
                )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._finalise_job(
                job.id,
                state="completed",
                duration_ms=duration_ms,
                error=None,
            )

            logger.info(
                "event=backfill job_id=%s state=completed processed=%s matched=%s "
                "cache_hits=%s cache_misses=%s expanded_playlists=%s "
                "expanded_tracks=%s duration_ms=%s",
                job.id,
                processed,
                matched,
                cache_hits,
                cache_misses,
                playlists_expanded,
                tracks_added,
                duration_ms,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("event=backfill job_id=%s state=failed", job.id)
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            self._finalise_job(
                job.id,
                state="failed",
                duration_ms=duration_ms,
                error=str(exc),
            )

    # Candidate processing -----------------------------------------------

    def _process_candidate(
        self,
        candidate: CandidateItem,
        metadata_cache: Dict[str, Dict[str, Any]],
    ) -> Tuple[bool, bool]:
        key = self._build_cache_key(candidate)
        cache_hit = False
        metadata: Optional[Dict[str, Any]] = None

        if key:
            cached = self._get_cache_entry(key)
            if cached is not None:
                cache_hit = True
                track_id, album_id = cached
                metadata = self._fetch_track_metadata(track_id, album_id, metadata_cache)

        if metadata is None:
            cache_hit = False if key else cache_hit
            track = self._spotify.find_track_match(
                artist=candidate.artist,
                title=candidate.title,
                album=candidate.album,
                duration_ms=candidate.duration_ms,
            )
            if not track:
                return False, cache_hit

            metadata = self._extract_track_metadata(track)
            track_id = metadata.get("track_id")
            if not track_id:
                return False, cache_hit
            metadata_cache[track_id] = metadata
            if key:
                self._store_cache_entry(key, track_id, metadata.get("album_id"))

        self._update_ingest_item(candidate.id, metadata)
        return True, cache_hit

    def _load_candidates(self, limit: int) -> List[CandidateItem]:
        statement: Select[Tuple[int, str, str, Optional[str], Optional[int]]] = (
            select(
                IngestItem.id,
                IngestItem.artist,
                IngestItem.title,
                IngestItem.album,
                IngestItem.duration_sec,
            )
            .where(
                IngestItem.spotify_track_id.is_(None),
                IngestItem.artist.isnot(None),
                IngestItem.title.isnot(None),
                IngestItem.source_type != "LINK",
            )
            .order_by(IngestItem.created_at.asc())
            .limit(limit)
        )

        with session_scope() as session:
            rows = session.execute(statement).all()

        candidates: List[CandidateItem] = []
        for item_id, artist, title, album, duration_sec in rows:
            if not artist or not title:
                continue
            duration_ms = int(duration_sec * 1000) if duration_sec is not None else None
            candidates.append(
                CandidateItem(
                    id=int(item_id),
                    artist=str(artist),
                    title=str(title),
                    album=str(album) if album else None,
                    duration_ms=duration_ms,
                )
            )
        return candidates

    def _update_ingest_item(self, item_id: int, metadata: Dict[str, Any]) -> None:
        duration_ms = metadata.get("duration_ms")
        duration_sec = int(round(duration_ms / 1000)) if duration_ms else None

        with session_scope() as session:
            item = session.get(IngestItem, item_id)
            if item is None:
                return

            item.spotify_track_id = metadata.get("track_id")
            item.spotify_album_id = metadata.get("album_id")
            item.isrc = metadata.get("isrc")
            if duration_sec:
                item.duration_sec = duration_sec
            session.add(item)

    # Playlist expansion -------------------------------------------------

    def _expand_playlists(self, job_id: str) -> Tuple[int, int]:
        playlists = self._load_playlist_links()
        if not playlists:
            return 0, 0

        total_playlists = 0
        total_tracks = 0

        for playlist in playlists:
            expanded = self._expand_playlist(job_id, playlist)
            if expanded is None:
                continue
            total_playlists += 1
            total_tracks += expanded

        return total_playlists, total_tracks

    def _load_playlist_links(self) -> List[PlaylistLink]:
        statement = (
            select(IngestItem.id, IngestItem.job_id, IngestItem.playlist_url)
            .where(
                IngestItem.source_type == "LINK",
                IngestItem.playlist_url.isnot(None),
                IngestItem.state.in_(
                    [
                        IngestItemState.REGISTERED.value,
                        IngestItemState.NORMALIZED.value,
                    ]
                ),
            )
            .order_by(IngestItem.created_at.asc())
        )

        with session_scope() as session:
            rows = session.execute(statement).all()

        links: List[PlaylistLink] = []
        for item_id, job_id, url in rows:
            if not url:
                continue
            links.append(PlaylistLink(item_id=int(item_id), job_id=str(job_id), url=str(url)))
        return links

    def _expand_playlist(self, job_id: str, playlist: PlaylistLink) -> Optional[int]:
        playlist_id = self._extract_playlist_id(playlist.url)
        if not playlist_id:
            self._mark_playlist_complete(playlist.item_id, error="invalid_url")
            return None

        tracks = self._fetch_playlist_tracks(playlist_id)
        if not tracks:
            self._mark_playlist_complete(playlist.item_id, error="empty_playlist")
            return 0

        fingerprints = [
            self._hash_parts("playlist", playlist_id, track.get("id") or track.get("name"))
            for track in tracks
        ]

        existing_fingerprints: set[str] = set()
        if fingerprints:
            with session_scope() as session:
                existing_fingerprints = {
                    row[0]
                    for row in session.execute(
                        select(IngestItem.source_fingerprint).where(
                            IngestItem.source_fingerprint.in_(fingerprints)
                        )
                    )
                }

        created = 0
        now = datetime.utcnow()

        with session_scope() as session:
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                track_id = track.get("id")
                fingerprint = self._hash_parts(
                    "playlist", playlist_id, track_id or track.get("name")
                )
                if fingerprint in existing_fingerprints:
                    continue

                existing_fingerprints.add(fingerprint)

                album = track.get("album") if isinstance(track.get("album"), dict) else {}
                external_ids = track.get("external_ids")
                isrc = None
                if isinstance(external_ids, dict):
                    isrc_value = external_ids.get("isrc")
                    if isrc_value:
                        isrc = str(isrc_value)

                duration_ms = track.get("duration_ms")
                duration_sec = (
                    int(round(duration_ms / 1000))
                    if isinstance(duration_ms, (int, float))
                    else None
                )

                artist_names = SpotifyClient._extract_artist_names(track.get("artists"))
                dedupe_hash = self._hash_parts(
                    artist_names,
                    track.get("name"),
                    album.get("name") if isinstance(album, dict) else album,
                    track_id or playlist_id,
                )

                item = IngestItem(
                    job_id=playlist.job_id,
                    source_type="PRO_PLAYLIST_EXPANSION",
                    playlist_url=playlist.url,
                    raw_line=None,
                    artist=artist_names or None,
                    title=str(track.get("name")) if track.get("name") else None,
                    album=album.get("name") if isinstance(album, dict) else None,
                    duration_sec=duration_sec,
                    spotify_track_id=str(track_id) if track_id else None,
                    spotify_album_id=str(album.get("id")) if isinstance(album, dict) else None,
                    isrc=isrc,
                    dedupe_hash=dedupe_hash,
                    source_fingerprint=fingerprint,
                    state=IngestItemState.REGISTERED.value,
                    error=None,
                    created_at=now,
                )
                session.add(item)
                created += 1

            playlist_item = session.get(IngestItem, playlist.item_id)
            if playlist_item is not None:
                playlist_item.state = IngestItemState.COMPLETED.value
                playlist_item.error = None
                session.add(playlist_item)

        return created

    def _fetch_playlist_tracks(self, playlist_id: str) -> List[Dict[str, Any]]:
        tracks: List[Dict[str, Any]] = []
        offset = 0
        limit = 100

        while True:
            try:
                response = self._spotify.get_playlist_items(playlist_id, limit=limit, offset=offset)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "event=backfill playlist_fetch_failed playlist_id=%s error=%s",
                    playlist_id,
                    exc,
                )
                break

            if not isinstance(response, dict):
                break

            items = response.get("items")
            if not isinstance(items, list) or not items:
                break

            for entry in items:
                if isinstance(entry, dict):
                    track = entry.get("track")
                    if isinstance(track, dict):
                        tracks.append(track)

            offset += len(items)

            total = response.get("total")
            total_int: Optional[int]
            try:
                total_int = int(total) if total is not None else None
            except (TypeError, ValueError):
                total_int = None

            if total_int is not None and offset >= total_int:
                break
            if len(items) < limit:
                break

        return tracks

    # Persistence helpers ------------------------------------------------

    def _update_job_state(self, job_id: str, *, state: str, error: Optional[str]) -> None:
        with session_scope() as session:
            record = session.get(BackfillJob, job_id)
            if record is None:
                return
            record.state = state
            record.error = error
            record.updated_at = datetime.utcnow()
            session.add(record)

    def _persist_progress(
        self,
        job_id: str,
        *,
        processed: int,
        matched: int,
        cache_hits: int,
        cache_misses: int,
        expanded_playlists: int,
        expanded_tracks: int,
    ) -> None:
        with session_scope() as session:
            record = session.get(BackfillJob, job_id)
            if record is None:
                return
            record.processed_items = processed
            record.matched_items = matched
            record.cache_hits = cache_hits
            record.cache_misses = cache_misses
            record.expanded_playlists = expanded_playlists
            record.expanded_tracks = expanded_tracks
            record.updated_at = datetime.utcnow()
            session.add(record)

    def _finalise_job(
        self,
        job_id: str,
        *,
        state: str,
        duration_ms: int,
        error: Optional[str],
    ) -> None:
        with session_scope() as session:
            record = session.get(BackfillJob, job_id)
            if record is None:
                return
            record.state = state
            record.duration_ms = duration_ms
            record.error = error
            record.updated_at = datetime.utcnow()
            session.add(record)

    def _mark_playlist_complete(self, item_id: int, *, error: Optional[str]) -> None:
        with session_scope() as session:
            item = session.get(IngestItem, item_id)
            if item is None:
                return
            item.state = IngestItemState.COMPLETED.value
            item.error = error
            session.add(item)

    # Cache helpers ------------------------------------------------------

    def _build_cache_key(self, candidate: CandidateItem) -> Optional[str]:
        artist = SpotifyClient._normalise_text(candidate.artist)
        title = SpotifyClient._normalise_text(candidate.title)
        album = SpotifyClient._normalise_text(candidate.album)
        if not artist or not title:
            return None
        return f"{artist}|{title}|{album}".strip("|")

    def _get_cache_entry(self, key: str) -> Optional[Tuple[str, Optional[str]]]:
        now = datetime.utcnow()
        with session_scope() as session:
            entry = session.get(SpotifyCache, key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                session.delete(entry)
                return None
            if not entry.track_id:
                return None
            return entry.track_id, entry.album_id

    def _store_cache_entry(self, key: str, track_id: str, album_id: Optional[str]) -> None:
        if not track_id:
            return
        expires_at = datetime.utcnow() + timedelta(seconds=self._cache_ttl)
        with session_scope() as session:
            entry = session.get(SpotifyCache, key)
            if entry is None:
                entry = SpotifyCache(
                    key=key,
                    track_id=track_id,
                    album_id=album_id,
                    expires_at=expires_at,
                )
                session.add(entry)
            else:
                entry.track_id = track_id
                entry.album_id = album_id
                entry.expires_at = expires_at
                session.add(entry)

    def _fetch_track_metadata(
        self,
        track_id: str,
        album_id: Optional[str],
        cache: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not track_id:
            return {"track_id": None, "album_id": album_id, "isrc": None, "duration_ms": None}

        if track_id in cache:
            return cache[track_id]

        try:
            track = self._spotify.get_track_details(track_id)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.debug("Spotify track lookup failed for %s: %s", track_id, exc)
            track = {}

        metadata = self._extract_track_metadata(track)
        if not metadata.get("album_id") and album_id:
            metadata["album_id"] = album_id
        cache[track_id] = metadata
        return metadata

    @staticmethod
    def _extract_track_metadata(track: Dict[str, Any]) -> Dict[str, Any]:
        album = track.get("album") if isinstance(track.get("album"), dict) else {}
        external_ids = track.get("external_ids")
        isrc = None
        if isinstance(external_ids, dict):
            value = external_ids.get("isrc")
            if value:
                isrc = str(value)

        duration_ms = track.get("duration_ms")
        if not isinstance(duration_ms, (int, float)):
            duration_ms = None

        metadata = {
            "track_id": str(track.get("id")) if track.get("id") else None,
            "album_id": str(album.get("id")) if isinstance(album, dict) else None,
            "isrc": isrc,
            "duration_ms": int(duration_ms) if duration_ms is not None else None,
        }
        return metadata

    # Utility helpers ----------------------------------------------------

    def _ensure_authenticated(self) -> None:
        try:
            authenticated = self._spotify.is_authenticated()
        except Exception:  # pragma: no cover - defensive guard
            authenticated = False
        if not authenticated:
            raise PermissionError("Spotify authentication required for backfill")

    def _resolve_limit(self, max_items: Optional[int]) -> int:
        if max_items is None:
            return self._default_limit
        try:
            parsed = int(max_items)
        except (TypeError, ValueError):
            return self._default_limit
        return max(1, min(parsed, self._default_limit))

    def _count_candidates(self) -> int:
        statement = (
            select(func.count())
            .select_from(IngestItem)
            .where(
                IngestItem.spotify_track_id.is_(None),
                IngestItem.artist.isnot(None),
                IngestItem.title.isnot(None),
                IngestItem.source_type != "LINK",
            )
        )
        with session_scope() as session:
            total = session.execute(statement).scalar()
        return int(total or 0)

    @staticmethod
    def _hash_parts(*parts: object) -> str:
        digest = hashlib.sha256()
        for part in parts:
            digest.update(str(part).strip().lower().encode("utf-8"))
            digest.update(b"::")
        return digest.hexdigest()

    @staticmethod
    def _extract_playlist_id(url: str) -> Optional[str]:
        if not url:
            return None
        if url.startswith("spotify:playlist:"):
            return url.split(":")[-1]

        parsed = urlparse(url)
        if not parsed.path:
            return None
        parts = [segment for segment in parsed.path.split("/") if segment]
        if len(parts) >= 2 and parts[0] == "playlist":
            return parts[1]
        return None
