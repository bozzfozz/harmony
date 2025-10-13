"""Database access helpers for the watchlist worker.

The worker orchestrates asynchronous processing but our SQLAlchemy
integration remains synchronous.  To keep scheduling flexible the DAO
exposes plain synchronous primitives; the worker decides whether to wrap
them in ``asyncio.to_thread`` or use an async session depending on its
configuration.  Only the minimal operations required by the worker are
implemented: loading artists, updating their state and creating download
records for the sync worker.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, func, or_, select

from app.db import session_scope
from app.models import Download, WatchlistArtist

_UNSET = object()


@dataclass(slots=True)
class WatchlistArtistRow:
    """Lightweight representation of a watchlist artist."""

    id: int
    spotify_artist_id: str
    name: str
    last_checked: datetime | None
    retry_block_until: datetime | None


class WatchlistDAO:
    """Async-friendly access layer for watchlist related persistence."""

    def get_artist(self, artist_id: int) -> WatchlistArtistRow | None:
        """Return a single watchlist artist by primary key."""

        def _query() -> WatchlistArtistRow | None:
            with session_scope() as session:
                record = session.get(WatchlistArtist, int(artist_id))
                if record is None:
                    return None
                return WatchlistArtistRow(
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
    ) -> list[WatchlistArtistRow]:
        """Return a batch of artists ordered by the ``last_checked`` timestamp."""

        if limit <= 0:
            return []

        def _query() -> list[WatchlistArtistRow]:
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
                    WatchlistArtistRow(
                        id=record.id,
                        spotify_artist_id=record.spotify_artist_id,
                        name=record.name,
                        last_checked=record.last_checked,
                        retry_block_until=record.retry_block_until,
                    )
                    for record in records
                ]

        return _query()

    def mark_in_progress(self, artist_id: int) -> bool:
        """Ensure the artist still exists before processing."""

        def _mark() -> bool:
            with session_scope() as session:
                record = session.get(WatchlistArtist, int(artist_id))
                if record is None:
                    return False
                # No state transition is persisted yet, we merely guard against
                # concurrent deletions of the artist entry.
                return True

        return _mark()

    def mark_success(
        self,
        artist_id: int,
        *,
        checked_at: datetime | None = None,
    ) -> None:
        """Record that the artist finished processing."""

        timestamp = checked_at or datetime.utcnow()

        def _mark() -> None:
            with session_scope() as session:
                record = session.get(WatchlistArtist, int(artist_id))
                if record is None:
                    return
                record.last_checked = timestamp
                record.last_scan_at = timestamp
                record.retry_block_until = None
                record.updated_at = datetime.utcnow()
                session.add(record)

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
                record.last_scan_at = next_time
                if retry_block_until is not _UNSET:
                    record.retry_block_until = retry_block_until
                record.updated_at = datetime.utcnow()
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
        payload: dict[str, Any],
    ) -> int | None:
        """Insert a new download row and return its identifier."""

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


__all__ = ["WatchlistDAO", "WatchlistArtistRow"]
