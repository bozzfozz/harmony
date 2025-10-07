"""Persistence helpers for the artist workflow orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import Select, and_, func, or_, select

from app.db import session_scope
from app.models import ArtistKnownReleaseRecord, Download, WatchlistArtist
from app.services.artist_delta import ArtistKnownRelease


_UNSET = object()


@dataclass(slots=True)
class ArtistWorkflowArtistRow:
    """Lightweight representation of an artist monitored by the workflow."""

    id: int
    spotify_artist_id: str
    name: str
    last_checked: datetime | None
    retry_block_until: datetime | None


class ArtistWorkflowDAO:
    """Async-friendly access layer for orchestrating artist workflows."""

    def get_artist(self, artist_id: int) -> ArtistWorkflowArtistRow | None:
        """Return a single artist row by primary key."""

        def _query() -> ArtistWorkflowArtistRow | None:
            with session_scope() as session:
                record = session.get(WatchlistArtist, int(artist_id))
                if record is None:
                    return None
                return ArtistWorkflowArtistRow(
                    id=record.id,
                    spotify_artist_id=record.spotify_artist_id,
                    name=record.name,
                    last_checked=record.last_checked,
                    retry_block_until=record.retry_block_until,
                )

        return _query()

    def load_batch(
        self,
        limit: int,
        *,
        cutoff: datetime | None = None,
    ) -> list[ArtistWorkflowArtistRow]:
        """Return a batch of artists ordered by their ``last_checked`` timestamp."""

        if limit <= 0:
            return []

        def _query() -> list[ArtistWorkflowArtistRow]:
            now = cutoff or datetime.utcnow()
            with session_scope() as session:
                statement: Select[tuple[WatchlistArtist]] = (
                    select(WatchlistArtist)
                    .order_by(
                        func.coalesce(WatchlistArtist.last_checked, datetime.min),
                        WatchlistArtist.id.asc(),
                    )
                    .limit(limit)
                )
                statement = statement.where(
                    and_(
                        or_(
                            WatchlistArtist.retry_block_until.is_(None),
                            WatchlistArtist.retry_block_until <= now,
                        ),
                        or_(
                            WatchlistArtist.last_checked.is_(None),
                            WatchlistArtist.last_checked <= now,
                        ),
                    )
                )
                records = session.execute(statement).scalars().all()
                return [
                    ArtistWorkflowArtistRow(
                        id=record.id,
                        spotify_artist_id=record.spotify_artist_id,
                        name=record.name,
                        last_checked=record.last_checked,
                        retry_block_until=record.retry_block_until,
                    )
                    for record in records
                ]

        return _query()

    def load_known_releases(self, artist_id: int) -> dict[str, ArtistKnownRelease]:
        """Return persisted known releases for the given artist."""

        def _query() -> dict[str, ArtistKnownRelease]:
            with session_scope() as session:
                statement = select(ArtistKnownReleaseRecord).where(
                    ArtistKnownReleaseRecord.artist_id == int(artist_id)
                )
                records = session.execute(statement).scalars().all()
                known: dict[str, ArtistKnownRelease] = {}
                for record in records:
                    track_id = (record.track_id or "").strip()
                    if not track_id:
                        continue
                    known[track_id] = ArtistKnownRelease(
                        track_id=track_id,
                        etag=record.etag,
                        fetched_at=record.fetched_at,
                    )
                return known

        return _query()

    def mark_success(
        self,
        artist_id: int,
        *,
        checked_at: datetime | None = None,
        known_releases: Sequence[ArtistKnownRelease] | None = None,
    ) -> None:
        """Record a successful run and optionally persist known releases."""

        timestamp = checked_at or datetime.utcnow()

        def _mark() -> None:
            with session_scope() as session:
                record = session.get(WatchlistArtist, int(artist_id))
                if record is None:
                    return
                record.last_checked = timestamp
                record.retry_block_until = None
                session.add(record)
                if known_releases:
                    for release in known_releases:
                        self._upsert_known_release(
                            session,
                            int(artist_id),
                            release,
                            default_fetched_at=timestamp,
                        )

        _mark()

    def mark_failed(
        self,
        artist_id: int,
        *,
        reason: str,
        retry_at: datetime | None = None,
        retry_block_until: datetime | None | object = _UNSET,
    ) -> None:
        """Persist the failure outcome along with the next retry timestamp."""

        next_time = retry_at or datetime.utcnow()

        def _mark() -> None:
            with session_scope() as session:
                record = session.get(WatchlistArtist, int(artist_id))
                if record is None:
                    return
                record.last_checked = next_time
                if retry_block_until is not _UNSET:
                    record.retry_block_until = retry_block_until
                session.add(record)

        _mark()

    def load_existing_track_ids(self, track_ids: Sequence[str]) -> set[str]:
        """Return already scheduled Spotify track identifiers."""

        if not track_ids:
            return set()

        def _query() -> set[str]:
            with session_scope() as session:
                statement = (
                    select(Download.spotify_track_id)
                    .where(Download.spotify_track_id.in_(track_ids))
                    .where(Download.state.notin_(["failed", "cancelled", "dead_letter"]))
                )
                values = session.execute(statement).scalars().all()
                return {str(value) for value in values if value}

        return _query()

    def create_download_record(
        self,
        *,
        username: str,
        filename: str,
        priority: int,
        spotify_track_id: str,
        spotify_album_id: str,
        payload: Mapping[str, Any],
        artist_id: int | None = None,
        known_release: ArtistKnownRelease | None = None,
    ) -> int | None:
        """Insert a new download row and optionally persist the known release."""

        def _create() -> int | None:
            with session_scope() as session:
                download = Download(
                    filename=filename,
                    state="queued",
                    progress=0.0,
                    username=username,
                    priority=priority,
                    spotify_track_id=spotify_track_id or None,
                    spotify_album_id=spotify_album_id or None,
                )
                session.add(download)
                session.flush()
                payload_copy = dict(payload)
                payload_copy.setdefault("filename", filename)
                payload_copy["download_id"] = download.id
                payload_copy["priority"] = priority
                download.request_payload = payload_copy
                session.add(download)
                if known_release is not None:
                    if artist_id is None:
                        raise ValueError("artist_id is required when known_release is provided")
                    self._upsert_known_release(
                        session,
                        int(artist_id),
                        known_release,
                        default_fetched_at=datetime.utcnow(),
                    )
                return int(download.id)

        return _create()

    def mark_download_failed(self, download_id: int, reason: str) -> None:
        """Persist a download failure in case enqueueing the job fails."""

        def _mark() -> None:
            now = datetime.utcnow()
            with session_scope() as session:
                record = session.get(Download, int(download_id))
                if record is None:
                    return
                record.state = "failed"
                record.updated_at = now
                payload = dict(record.request_payload or {})
                payload["error"] = reason
                record.request_payload = payload
                session.add(record)

        _mark()

    def _upsert_known_release(
        self,
        session,
        artist_id: int,
        release: ArtistKnownRelease,
        *,
        default_fetched_at: datetime | None = None,
    ) -> None:
        """Insert or update a known release row for the artist."""

        track_id = (release.track_id or "").strip()
        if not track_id:
            return
        fetched_at = release.fetched_at or default_fetched_at or datetime.utcnow()

        statement = select(ArtistKnownReleaseRecord).where(
            ArtistKnownReleaseRecord.artist_id == artist_id,
            ArtistKnownReleaseRecord.track_id == track_id,
        )
        existing = session.execute(statement).scalars().first()
        if existing is None:
            existing = ArtistKnownReleaseRecord(
                artist_id=artist_id,
                track_id=track_id,
            )
        existing.etag = release.etag
        existing.fetched_at = fetched_at
        session.add(existing)


__all__ = ["ArtistWorkflowDAO", "ArtistWorkflowArtistRow"]

