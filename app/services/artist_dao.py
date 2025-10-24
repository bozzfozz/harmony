"""Persistence helpers for the artist synchronisation workflow."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
import hashlib
import json
from typing import SupportsInt

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


def _normalise_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=None)
    return value.astimezone(UTC).replace(tzinfo=None)


def _coerce_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    if isinstance(value, SupportsInt):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
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
    metadata: Mapping[str, object]
    version: str | None
    etag: str
    updated_at: datetime
    created_at: datetime
    inactive_at: datetime | None
    inactive_reason: str | None


@dataclass(slots=True, frozen=True)
class ArtistWatchlistItem:
    artist_key: str
    priority: int
    last_enqueued_at: datetime | None
    last_synced_at: datetime | None
    cooldown_until: datetime | None


@dataclass(slots=True, frozen=True)
class ArtistWatchlistEntryRow(ArtistWatchlistItem):
    created_at: datetime
    updated_at: datetime


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
                    if record.inactive_at is not None or record.inactive_reason:
                        record.inactive_at = None
                        record.inactive_reason = None
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
                            (record.release_date.isoformat() if record.release_date else ""),
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
                        metadata=dict(record.metadata_json or {}),
                        version=record.version,
                        etag=record.etag,
                        updated_at=record.updated_at,
                        created_at=record.created_at,
                        inactive_at=record.inactive_at,
                        inactive_reason=record.inactive_reason,
                    )
                )
        return rows

    def refresh_artist_version(self, artist_key: str) -> ArtistRow | None:
        key = (artist_key or "").strip()
        if not key:
            return None

        timestamp = self._now()
        statement: Select[ArtistRecord] = (
            select(ArtistRecord).where(ArtistRecord.artist_key == key).limit(1)
        )

        with session_scope() as session:
            artist = session.execute(statement).scalars().first()
            if artist is None:
                return None
            release_stmt: Select[str] = (
                select(ArtistReleaseRecord.etag)
                .where(ArtistReleaseRecord.artist_key == key)
                .where(ArtistReleaseRecord.inactive_at.is_(None))
                .order_by(ArtistReleaseRecord.id.asc())
            )
            active_etags = [
                value
                for value in session.execute(release_stmt).scalars().all()
                if isinstance(value, str) and value
            ]
            artist.updated_at = timestamp
            artist.etag = _hash_values(
                artist.name,
                tuple(artist.genres or []),
                tuple(artist.images or []),
                artist.updated_at.isoformat(timespec="seconds"),
                tuple(active_etags),
            )
            artist.version = artist.etag
            session.add(artist)
            session.flush()
            session.refresh(artist)
            return ArtistRow(
                id=int(artist.id),
                artist_key=artist.artist_key,
                source=artist.source,
                source_id=artist.source_id,
                name=artist.name,
                genres=tuple(artist.genres or []),
                images=tuple(artist.images or []),
                popularity=_coerce_int(artist.popularity),
                metadata=dict(artist.metadata_json or {}),
                version=artist.version,
                etag=artist.etag,
                updated_at=artist.updated_at,
                created_at=artist.created_at,
            )

    def get_artist(self, artist_key: str) -> ArtistRow | None:
        key = (artist_key or "").strip()
        if not key:
            return None
        statement: Select[ArtistRecord] = (
            select(ArtistRecord).where(ArtistRecord.artist_key == key).limit(1)
        )
        with session_scope() as session:
            record = session.execute(statement).scalars().first()
            if record is None:
                return None
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

    def get_artist_releases(
        self, artist_key: str, *, include_inactive: bool = False
    ) -> list[ArtistReleaseRow]:
        key = (artist_key or "").strip()
        if not key:
            return []
        statement: Select[ArtistReleaseRecord] = select(ArtistReleaseRecord).where(
            ArtistReleaseRecord.artist_key == key
        )
        if not include_inactive:
            statement = statement.where(ArtistReleaseRecord.inactive_at.is_(None))
        statement = statement.order_by(
            desc(ArtistReleaseRecord.release_date),
            desc(ArtistReleaseRecord.updated_at),
            ArtistReleaseRecord.id.asc(),
        )
        with session_scope() as session:
            records = session.execute(statement).scalars().all()
            rows: list[ArtistReleaseRow] = []
            for record in records:
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
                        metadata=dict(record.metadata_json or {}),
                        version=record.version,
                        etag=record.etag,
                        updated_at=record.updated_at,
                        created_at=record.created_at,
                        inactive_at=record.inactive_at,
                        inactive_reason=record.inactive_reason,
                    )
                )
            return rows

    def mark_releases_inactive(
        self,
        release_ids: Sequence[int],
        *,
        reason: str,
        hard_delete: bool = False,
    ) -> list[ArtistReleaseRow]:
        ids = {
            int(value) for value in release_ids if isinstance(value, int) or str(value).isdigit()
        }
        if not ids:
            return []
        timestamp = self._now()
        updated: list[ArtistReleaseRow] = []
        with session_scope() as session:
            statement = select(ArtistReleaseRecord).where(ArtistReleaseRecord.id.in_(ids))
            records = session.execute(statement).scalars().all()
            if hard_delete:
                for record in records:
                    session.delete(record)
                return []
            for record in records:
                if record.inactive_at and record.inactive_reason == reason:
                    continue
                record.inactive_at = timestamp
                record.inactive_reason = reason
                record.updated_at = timestamp
                session.add(record)
                session.flush()
                session.refresh(record)
                updated.append(
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
                        metadata=dict(record.metadata_json or {}),
                        version=record.version,
                        etag=record.etag,
                        updated_at=record.updated_at,
                        created_at=record.created_at,
                        inactive_at=record.inactive_at,
                        inactive_reason=record.inactive_reason,
                    )
                )
        return updated

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
                    last_synced_at=record.last_synced_at,
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

    def mark_synced(
        self,
        artist_key: str,
        *,
        synced_at: datetime,
        cooldown_until: datetime | None = None,
        priority_decay: int | None = None,
    ) -> bool:
        key = (artist_key or "").strip()
        if not key:
            return False
        timestamp = synced_at.replace(tzinfo=None)
        cooldown = _normalise_datetime(cooldown_until)
        with session_scope() as session:
            record = session.get(ArtistWatchlistEntry, key)
            if record is None:
                return False
            record.last_synced_at = timestamp
            record.cooldown_until = cooldown
            if priority_decay:
                try:
                    decay = int(priority_decay)
                except (TypeError, ValueError):
                    decay = 0
                if decay > 0:
                    current = int(record.priority or 0)
                    record.priority = max(0, current - decay)
            record.updated_at = timestamp
            session.add(record)
        return True

    def list_watchlist_entries(
        self, *, limit: int, offset: int = 0
    ) -> tuple[list[ArtistWatchlistEntryRow], int]:
        resolved_limit = max(0, limit)
        resolved_offset = max(0, offset)
        with session_scope() as session:
            total = session.execute(
                select(func.count()).select_from(ArtistWatchlistEntry)
            ).scalar_one()
            if resolved_limit == 0 or total == 0 or resolved_offset >= total:
                return ([], int(total))
            statement: Select[ArtistWatchlistEntry] = (
                select(ArtistWatchlistEntry)
                .order_by(
                    desc(ArtistWatchlistEntry.priority),
                    func.coalesce(ArtistWatchlistEntry.cooldown_until, datetime.min),
                    ArtistWatchlistEntry.artist_key.asc(),
                )
                .offset(resolved_offset)
                .limit(resolved_limit)
            )
            records = session.execute(statement).scalars().all()
            items: list[ArtistWatchlistEntryRow] = []
            for record in records:
                items.append(
                    ArtistWatchlistEntryRow(
                        artist_key=record.artist_key,
                        priority=int(record.priority or 0),
                        last_enqueued_at=record.last_enqueued_at,
                        last_synced_at=record.last_synced_at,
                        cooldown_until=record.cooldown_until,
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    )
                )
            return items, int(total)

    def upsert_watchlist_entry(
        self,
        artist_key: str,
        *,
        priority: int = 0,
        cooldown_until: datetime | None = None,
    ) -> ArtistWatchlistEntryRow:
        key = (artist_key or "").strip()
        if not key:
            raise ValueError("artist_key must be provided")
        timestamp = self._now()
        normalised_cooldown = _normalise_datetime(cooldown_until)
        with session_scope() as session:
            record = session.get(ArtistWatchlistEntry, key)
            if record is None:
                record = ArtistWatchlistEntry(
                    artist_key=key,
                    priority=int(priority or 0),
                    cooldown_until=normalised_cooldown,
                    last_synced_at=None,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            else:
                record.priority = int(priority or 0)
                record.cooldown_until = normalised_cooldown
                record.updated_at = timestamp
            session.add(record)
            session.flush()
            session.refresh(record)
            return ArtistWatchlistEntryRow(
                artist_key=record.artist_key,
                priority=int(record.priority or 0),
                last_enqueued_at=record.last_enqueued_at,
                last_synced_at=record.last_synced_at,
                cooldown_until=record.cooldown_until,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )

    def remove_watchlist_entry(self, artist_key: str) -> bool:
        key = (artist_key or "").strip()
        if not key:
            return False
        with session_scope() as session:
            record = session.get(ArtistWatchlistEntry, key)
            if record is None:
                return False
            session.delete(record)
        return True


__all__ = [
    "ArtistDao",
    "ArtistReleaseRow",
    "ArtistReleaseUpsertDTO",
    "ArtistRow",
    "ArtistUpsertDTO",
    "ArtistWatchlistEntryRow",
    "ArtistWatchlistItem",
    "build_artist_key",
]
