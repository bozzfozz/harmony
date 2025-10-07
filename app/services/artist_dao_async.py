"""Async DAO helpers for watchlist artists."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WatchlistArtist


_MIN_COOLDOWN_SECONDS = 900
_MAX_COOLDOWN_SECONDS = 14_400


@dataclass(slots=True, frozen=True)
class WatchlistArtistDueRow:
    """Lightweight representation of a watchlist artist ready for scanning."""

    id: int
    spotify_artist_id: str
    name: str
    source_artist_id: int | None
    priority: int
    cooldown_s: int
    last_scan_at: datetime | None
    retry_block_until: datetime | None
    last_hash: str | None
    retry_budget_left: int | None
    stop_reason: str | None


class ArtistWatchlistAsyncDAO:
    """Async-first DAO exposing scheduling primitives for watchlist artists."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_due(self, limit: int) -> list[WatchlistArtistDueRow]:
        """Return artists that are ready for scanning ordered by priority."""

        if limit <= 0:
            return []

        now = datetime.utcnow()
        batch_size = max(limit * 2, 50)
        offset = 0
        due: list[WatchlistArtistDueRow] = []
        seen_ids: set[int] = set()

        base_stmt: Select[tuple[WatchlistArtist]] = (
            select(WatchlistArtist)
            .where(
                and_(
                    or_(
                        WatchlistArtist.stop_reason.is_(None),
                        WatchlistArtist.stop_reason == "",
                    ),
                    or_(
                        WatchlistArtist.retry_budget_left.is_(None),
                        WatchlistArtist.retry_budget_left > 0,
                    ),
                    or_(
                        WatchlistArtist.retry_block_until.is_(None),
                        WatchlistArtist.retry_block_until <= now,
                    ),
                )
            )
            .order_by(
                WatchlistArtist.priority.desc(),
                case((WatchlistArtist.last_scan_at.is_(None), 0), else_=1),
                WatchlistArtist.last_scan_at.asc(),
                WatchlistArtist.id.asc(),
            )
        )

        while len(due) < limit:
            stmt = base_stmt.offset(offset).limit(batch_size)
            rows = (await self._session.execute(stmt)).scalars().all()
            if not rows:
                break
            offset += len(rows)
            for record in rows:
                if record.id in seen_ids:
                    continue
                if self._is_due(record, now):
                    seen_ids.add(record.id)
                    due.append(self._to_row(record))
                    if len(due) >= limit:
                        break
        return due[:limit]

    async def mark_scanned(self, artist_id: int, content_hash: str | None) -> bool:
        """Persist the last scan timestamp and fingerprint for an artist."""

        record = await self._session.get(WatchlistArtist, int(artist_id))
        if record is None:
            return False
        now = datetime.utcnow()
        record.last_scan_at = now
        record.last_checked = now
        record.last_hash = content_hash
        record.updated_at = now
        self._session.add(record)
        await self._session.commit()
        return True

    async def bump_cooldown(self, artist_id: int) -> int | None:
        """Increase the cooldown window for the given artist and return the new value."""

        record = await self._session.get(WatchlistArtist, int(artist_id))
        if record is None:
            return None
        now = datetime.utcnow()
        current = int(record.cooldown_s or 0)
        if current <= 0:
            next_value = _MIN_COOLDOWN_SECONDS
        else:
            next_value = min(current * 2, _MAX_COOLDOWN_SECONDS)
        record.cooldown_s = next_value
        record.last_scan_at = now
        record.last_checked = now
        record.updated_at = now
        self._session.add(record)
        await self._session.commit()
        return int(record.cooldown_s or 0)

    async def update_retry(self, artist_id: int, delta: int) -> int | None:
        """Update the retry budget for an artist, clamping the value at zero."""

        record = await self._session.get(WatchlistArtist, int(artist_id))
        if record is None:
            return None
        current = int(record.retry_budget_left or 0)
        new_value = current + int(delta)
        if new_value < 0:
            new_value = 0
        record.retry_budget_left = new_value
        record.updated_at = datetime.utcnow()
        self._session.add(record)
        await self._session.commit()
        return int(record.retry_budget_left or 0)

    @staticmethod
    def _is_due(record: WatchlistArtist, now: datetime) -> bool:
        if record.stop_reason and record.stop_reason.strip():
            return False
        if record.retry_budget_left is not None and record.retry_budget_left <= 0:
            return False
        if record.retry_block_until and record.retry_block_until > now:
            return False
        cooldown = int(record.cooldown_s or 0)
        last_scan = record.last_scan_at or record.last_checked
        if last_scan is None:
            return True
        if cooldown <= 0:
            return True
        return now - last_scan >= timedelta(seconds=cooldown)

    @staticmethod
    def _to_row(record: WatchlistArtist) -> WatchlistArtistDueRow:
        return WatchlistArtistDueRow(
            id=int(record.id),
            spotify_artist_id=record.spotify_artist_id,
            name=record.name,
            source_artist_id=record.source_artist_id,
            priority=int(record.priority or 0),
            cooldown_s=int(record.cooldown_s or 0),
            last_scan_at=record.last_scan_at or record.last_checked,
            retry_block_until=record.retry_block_until,
            last_hash=record.last_hash,
            retry_budget_left=record.retry_budget_left,
            stop_reason=record.stop_reason,
        )


__all__ = ["ArtistWatchlistAsyncDAO", "WatchlistArtistDueRow"]
