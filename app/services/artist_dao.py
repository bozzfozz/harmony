"""Persistence helpers for the artist synchronisation workflow."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Callable, Iterable, Mapping, Sequence

from sqlalchemy import Select, desc, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.db import session_scope
from app.models import ArtistRecord, ArtistReleaseRecord, ArtistWatchlistEntry


def _hash_values(*values: object) -> str:
    digest = hashlib.sha256()
    for value in values:
        if value is None:
            payload = b"<null>"
        elif isinstance(value, bytes):
            payload = value
        elif isinstance(value, str):
            payload = value.encode("utf-8")
        else:
            payload = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        digest.update(len(payload).to_bytes(4, "big"))
        digest.update(payload)
    return digest.hexdigest()[:32]


def _normalise_sequence(values: Iterable[object] | None) -> tuple[str, ...]:
    if not values:
        return ()
    seen: set[str] = set()
    normalised: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalised.append(text)
    normalised.sort(key=lambda item: item.casefold())
    return tuple(normalised)


def _normalise_metadata(metadata: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(metadata, Mapping):
        return {}
    result: dict[str, object] = {}
    for key, value in metadata.items():
        if not isinstance(key, str):
            continue
        result[key] = value
    return result


def _coerce_int(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_date(value: object | None) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10:
        text = text[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def build_artist_key(source: str, source_id: str | None) -> str:
    prefix = (source or "unknown").strip().lower()
    identifier = (source_id or "").strip()
    return f"{prefix}:{identifier}" if identifier else f"{prefix}:"


@dataclass(slots=True, frozen=True)
class ArtistUpsertDTO:
    artist_key: str
    source: str
    source_id: str | None
    name: str
    genres: tuple[str, ...] = field(default_factory=tuple)
    images: tuple[str, ...] = field(default_factory=tuple)
    popularity: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ArtistRow:
    id: int
    artist_key: str
    source: str
    source_id: str | None
    name: str
    genres: tuple[str, ...]
    images: tuple[str, ...]
    popularity: int | None
    metadata: Mapping[str, object]
    version: str
    etag: str
    updated_at: datetime
    created_at: datetime


@dataclass(slots=True, frozen=True)
class ArtistReleaseUpsertDTO:
    artist_key: str
    source: str
    source_id: str | None
    title: str
    release_date: object | None = None
    release_type: str | None = None
    total_tracks: int | None = None
    version: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ArtistReleaseRow:
    id: int
    artist_id: int
    artist_key: str
    source: str
    source_id: str | None
    title: str
    release_date: date | None
    release_type: str | None
    total_tracks: int | None
    version: str | None
    etag: str
    updated_at: datetime
    created_at: datetime


@dataclass(slots=True, frozen=True)
class ArtistWatchlistItem:
    artist_key: str
    priority: int
    last_enqueued_at: datetime | None
    cooldown_until: datetime | None


class ArtistDao:
    """Persistence facade handling artist related storage concerns."""

    def __init__(self, *, now_factory: Callable[[], datetime] | None = None) -> None:
        self._now_factory = now_factory or datetime.utcnow

    def _now(self) -> datetime:
        return self._now_factory().replace(tzinfo=None)

    def upsert_artist(self, dto: ArtistUpsertDTO) -> ArtistRow:
        payload = replace(
            dto,
            artist_key=dto.artist_key.strip(),
            source=(dto.source or "unknown").strip(),
            source_id=(dto.source_id or None),
            name=dto.name.strip(),
            genres=_normalise_sequence(dto.genres),
            images=_normalise_sequence(dto.images),
            popularity=_coerce_int(dto.popularity),
            metadata=_normalise_metadata(dto.metadata),
        )
        timestamp = self._now()

        for attempt in range(2):
            try:
                with session_scope() as session:
                    statement: Select[ArtistRecord] = (
                        select(ArtistRecord)
                        .where(ArtistRecord.artist_key == payload.artist_key)
                        .limit(1)
                    )
                    record = session.execute(statement).scalars().first()
                    if record is None:
                        record = ArtistRecord(
                            artist_key=payload.artist_key,
                            source=payload.source,
                            source_id=payload.source_id,
                            name=payload.name,
                            genres=list(payload.genres),
                            images=list(payload.images),
                            popularity=payload.popularity,
                            metadata_json=dict(payload.metadata),
                            created_at=timestamp,
                            updated_at=timestamp,
                            etag=_hash_values(
                                payload.name,
                                payload.genres,
                                payload.images,
                                timestamp.isoformat(timespec="seconds"),
                            ),
                        )
                        record.version = record.etag
                        session.add(record)
                    else:
                        changed = False
                        if record.name != payload.name:
                            record.name = payload.name
                            changed = True
                        if tuple(record.genres or []) != payload.genres:
                            record.genres = list(payload.genres)
                            changed = True
                        if tuple(record.images or []) != payload.images:
                            record.images = list(payload.images)
                            changed = True
                        if record.source != payload.source:
                            record.source = payload.source
                            changed = True
                        if record.source_id != payload.source_id:
                            record.source_id = payload.source_id
                            changed = True
                        if _coerce_int(record.popularity) != payload.popularity:
                            record.popularity = payload.popularity
                            changed = True
                        if (record.metadata_json or {}) != payload.metadata:
                            record.metadata_json = dict(payload.metadata)
                            changed = True
                        if changed:
                            record.updated_at = timestamp
                            record.etag = _hash_values(
                                record.name,
                                payload.genres,
                                payload.images,
                                record.updated_at.isoformat(timespec="seconds"),
                            )
                            record.version = record.etag
                        elif not record.etag:
                            record.etag = _hash_values(
                                record.name,
                                tuple(record.genres or []),
                                tuple(record.images or []),
                                record.updated_at.isoformat(timespec="seconds"),
                            )
                            record.version = record.etag
                        session.add(record)
                    session.flush()
                    session.refresh(record)
                    return ArtistRow(
                        id=int(record.id),
                        artist_key=record.artist_key,
                        source=record.source,
                        source_id=record.source_id,
                        name=record.name,
                        genres=tuple(record.genres or []),
                        images=tuple(record.images or []),
                        popularity=_coerce_int(record.popularity),
                        metadata=dict(record.metadata_json or {}),
                        version=record.version,
                        etag=record.etag,
                        updated_at=record.updated_at,
                        created_at=record.created_at,
                    )
            except IntegrityError:
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("Artist upsert failed after retries.")

    def upsert_releases(self, releases: Sequence[ArtistReleaseUpsertDTO]) -> list[ArtistReleaseRow]:
        if not releases:
            return []

        deduped: dict[tuple[str, str, str | None], ArtistReleaseUpsertDTO] = {}
        for item in releases:
            key = (
                item.artist_key.strip(),
                (item.source or "unknown").strip(),
                (item.source_id or None),
            )
            if key not in deduped:
                deduped[key] = replace(
                    item,
                    artist_key=key[0],
                    source=key[1],
                    source_id=key[2],
                    title=item.title.strip(),
                    release_type=(item.release_type or None),
                    total_tracks=_coerce_int(item.total_tracks),
                    metadata=_normalise_metadata(item.metadata),
                )

        artist_keys = {key[0] for key in deduped}
        if not artist_keys:
            return []

        timestamp = self._now()
        rows: list[ArtistReleaseRow] = []

        with session_scope() as session:
            artist_stmt = select(ArtistRecord).where(ArtistRecord.artist_key.in_(artist_keys))
            artist_map = {
                record.artist_key: record for record in session.execute(artist_stmt).scalars().all()
            }

            for dto in deduped.values():
                artist = artist_map.get(dto.artist_key)
                if artist is None:
                    continue
                release_date = _coerce_date(dto.release_date)
                statement: Select[ArtistReleaseRecord]
                statement = select(ArtistReleaseRecord).where(
                    ArtistReleaseRecord.artist_key == dto.artist_key,
                    ArtistReleaseRecord.source == dto.source,
                )
                if dto.source_id is not None:
                    statement = statement.where(ArtistReleaseRecord.source_id == dto.source_id)
                else:
                    statement = statement.where(
                        ArtistReleaseRecord.source_id.is_(None),
                        ArtistReleaseRecord.title == dto.title,
                    )
                statement = statement.limit(1)
                record = session.execute(statement).scalars().first()
                if record is None:
                    record = ArtistReleaseRecord(
                        artist_id=int(artist.id),
                        artist_key=dto.artist_key,
                        source=dto.source,
                        source_id=dto.source_id,
                        title=dto.title,
                        release_date=release_date,
                        release_type=dto.release_type,
                        total_tracks=_coerce_int(dto.total_tracks),
                        metadata_json=dict(dto.metadata),
                        created_at=timestamp,
                        updated_at=timestamp,
                        etag=_hash_values(
                            dto.title,
                            release_date.isoformat() if release_date else "",
                            dto.release_type or "",
                            timestamp.isoformat(timespec="seconds"),
                        ),
                    )
                    record.version = record.etag
                    session.add(record)
                else:
                    changed = False
                    if record.title != dto.title:
                        record.title = dto.title
                        changed = True
                    if record.release_type != dto.release_type:
                        record.release_type = dto.release_type
                        changed = True
                    if record.source_id != dto.source_id:
                        record.source_id = dto.source_id
                        changed = True
                    if record.artist_id != artist.id:
                        record.artist_id = artist.id
                        changed = True
                    if record.artist_key != dto.artist_key:
                        record.artist_key = dto.artist_key
                        changed = True
                    if _coerce_int(record.total_tracks) != dto.total_tracks:
                        record.total_tracks = dto.total_tracks
                        changed = True
                    if record.metadata_json != dto.metadata:
                        record.metadata_json = dict(dto.metadata)
                        changed = True
                    if record.release_date != release_date:
                        record.release_date = release_date
                        changed = True
                    if changed:
                        record.updated_at = timestamp
                        record.etag = _hash_values(
                            record.title,
                            release_date.isoformat() if release_date else "",
                            record.release_type or "",
                            record.updated_at.isoformat(timespec="seconds"),
                        )
                        record.version = record.etag
                    elif not record.etag:
                        record.etag = _hash_values(
                            record.title,
                            record.release_date.isoformat() if record.release_date else "",
                            record.release_type or "",
                            record.updated_at.isoformat(timespec="seconds"),
                        )
                        record.version = record.etag
                    session.add(record)
                session.flush()
                session.refresh(record)
                rows.append(
                    ArtistReleaseRow(
                        id=int(record.id),
                        artist_id=int(record.artist_id),
                        artist_key=record.artist_key,
                        source=record.source,
                        source_id=record.source_id,
                        title=record.title,
                        release_date=record.release_date,
                        release_type=record.release_type,
                        total_tracks=_coerce_int(record.total_tracks),
                        version=record.version,
                        etag=record.etag,
                        updated_at=record.updated_at,
                        created_at=record.created_at,
                    )
                )
        return rows

    def get_watchlist_batch(
        self,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> list[ArtistWatchlistItem]:
        if limit <= 0:
            return []
        cutoff = (now or self._now()).replace(tzinfo=None)
        statement: Select[ArtistWatchlistEntry] = (
            select(ArtistWatchlistEntry)
            .where(
                or_(
                    ArtistWatchlistEntry.cooldown_until.is_(None),
                    ArtistWatchlistEntry.cooldown_until <= cutoff,
                )
            )
            .order_by(
                desc(ArtistWatchlistEntry.priority),
                func.coalesce(ArtistWatchlistEntry.last_enqueued_at, datetime.min),
                ArtistWatchlistEntry.artist_key.asc(),
            )
            .limit(limit)
        )
        with session_scope() as session:
            records = session.execute(statement).scalars().all()
            return [
                ArtistWatchlistItem(
                    artist_key=record.artist_key,
                    priority=int(record.priority or 0),
                    last_enqueued_at=record.last_enqueued_at,
                    cooldown_until=record.cooldown_until,
                )
                for record in records
            ]

    def mark_enqueued(
        self,
        artist_key: str,
        now: datetime,
        *,
        cooldown_until: datetime | None = None,
    ) -> bool:
        timestamp = now.replace(tzinfo=None)
        with session_scope() as session:
            record = session.get(ArtistWatchlistEntry, artist_key)
            if record is None:
                return False
            record.last_enqueued_at = timestamp
            if cooldown_until is not None:
                record.cooldown_until = cooldown_until.replace(tzinfo=None)
            record.updated_at = timestamp
            session.add(record)
        return True


__all__ = [
    "ArtistDao",
    "ArtistReleaseRow",
    "ArtistReleaseUpsertDTO",
    "ArtistRow",
    "ArtistUpsertDTO",
    "ArtistWatchlistItem",
    "build_artist_key",
]
