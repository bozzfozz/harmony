"""Database-backed watchlist service exposed to the public API."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.errors import AppError, ErrorCode, NotFoundError
from app.logging import get_logger
from app.logging_events import log_event
from app.models import ArtistRecord, WatchlistArtist

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(slots=True)
class WatchlistEntry:
    """Representation of a persisted watchlist artist."""

    id: int
    artist_key: str
    priority: int
    paused: bool
    pause_reason: str | None
    resume_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class WatchlistService:
    """Manage watchlist entries and expose CRUD operations to the API layer."""

    session_factory: SessionFactory = field(default=session_scope, repr=False)
    _logger: Any = field(default_factory=lambda: get_logger(__name__), init=False, repr=False)

    def reset(self) -> None:
        """Reset persisted watchlist entries (primarily used in tests)."""

        with self.session_factory() as session:
            session.query(WatchlistArtist).delete(synchronize_session=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_entries(self) -> list[WatchlistEntry]:
        """Return watchlist entries sorted by priority and creation time."""

        with self.session_factory() as session:
            records = (
                session.execute(
                    select(WatchlistArtist).order_by(
                        WatchlistArtist.priority.desc(),
                        WatchlistArtist.created_at.asc(),
                        WatchlistArtist.id.asc(),
                    )
                )
                .scalars()
                .all()
            )
            return [self._to_entry(session, record) for record in records]

    def create_entry(self, *, artist_key: str, priority: int = 0) -> WatchlistEntry:
        key = self._normalise_key(artist_key)
        priority_value = self._validate_priority(priority)
        _, identifier = self._parse_artist_key(key)

        with self.session_factory() as session:
            existing = self._find_by_identifier(session, identifier)
            if existing is not None:
                log_event(
                    self._logger,
                    "service.call",
                    component="service.watchlist",
                    operation="create",
                    status="error",
                    entity_id=key,
                    error="artist_exists",
                )
                raise AppError(
                    "Artist already registered.",
                    code=ErrorCode.VALIDATION_ERROR,
                    http_status=409,
                    meta={"artist_key": key},
                )

            record = self._insert_record(session, key, identifier, priority_value)
            entry = self._to_entry(session, record)

        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="create",
            status="ok",
            entity_id=key,
            priority=priority_value,
        )
        return entry

    def get_entry(self, artist_key: str) -> WatchlistEntry:
        key = self._normalise_key(artist_key)
        _, identifier = self._parse_artist_key(key)

        with self.session_factory() as session:
            record = self._find_by_identifier(session, identifier)
            if record is None:
                raise NotFoundError("Watchlist entry not found.")
            return self._to_entry(session, record)

    def update_priority(self, *, artist_key: str, priority: int) -> WatchlistEntry:
        key = self._normalise_key(artist_key)
        priority_value = self._validate_priority(priority)
        _, identifier = self._parse_artist_key(key)

        with self.session_factory() as session:
            record = self._find_by_identifier(session, identifier)
            if record is None:
                raise NotFoundError("Watchlist entry not found.")
            record.priority = priority_value
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.flush()
            session.refresh(record)
            entry = self._to_entry(session, record)

        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="update_priority",
            status="ok",
            entity_id=key,
            priority=priority_value,
        )
        return entry

    def pause_entry(
        self,
        *,
        artist_key: str,
        reason: str | None = None,
        resume_at: datetime | None = None,
    ) -> WatchlistEntry:
        key = self._normalise_key(artist_key)
        pause_reason = self._normalise_reason(reason)
        _, identifier = self._parse_artist_key(key)
        resume_at_value = self._normalise_datetime(resume_at)

        with self.session_factory() as session:
            record = self._find_by_identifier(session, identifier)
            if record is None:
                raise NotFoundError("Watchlist entry not found.")
            record.stop_reason = pause_reason or "paused"
            record.retry_block_until = resume_at_value
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.flush()
            session.refresh(record)
            entry = self._to_entry(session, record)

        payload = {
            "component": "service.watchlist",
            "operation": "pause",
            "status": "ok",
            "entity_id": key,
        }
        if pause_reason:
            payload["reason"] = pause_reason
        if resume_at_value:
            payload["resume_at"] = (
                resume_at_value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
            )
        log_event(self._logger, "service.call", **payload)
        return entry

    def resume_entry(self, *, artist_key: str) -> WatchlistEntry:
        key = self._normalise_key(artist_key)
        _, identifier = self._parse_artist_key(key)

        with self.session_factory() as session:
            record = self._find_by_identifier(session, identifier)
            if record is None:
                raise NotFoundError("Watchlist entry not found.")
            record.stop_reason = None
            record.retry_block_until = None
            record.updated_at = datetime.utcnow()
            session.add(record)
            session.flush()
            session.refresh(record)
            entry = self._to_entry(session, record)

        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="resume",
            status="ok",
            entity_id=key,
        )
        return entry

    def remove_entry(self, *, artist_key: str) -> None:
        key = self._normalise_key(artist_key)
        _, identifier = self._parse_artist_key(key)

        with self.session_factory() as session:
            record = self._find_by_identifier(session, identifier)
            if record is None:
                raise NotFoundError("Watchlist entry not found.")
            session.delete(record)

        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="delete",
            status="ok",
            entity_id=key,
        )

    @staticmethod
    def _normalise_key(value: str) -> str:
        candidate = (value or "").strip()
        if not candidate:
            raise AppError(
                "artist_key must not be empty.",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            )
        return candidate

    @staticmethod
    def _validate_priority(value: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise AppError(
                "priority must be an integer.",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            ) from exc

    @staticmethod
    def _normalise_reason(reason: str | None) -> str | None:
        if reason is None:
            return None
        candidate = reason.strip()
        return candidate or None

    @staticmethod
    def _normalise_datetime(timestamp: datetime | None) -> datetime | None:
        if timestamp is None:
            return None
        if timestamp.tzinfo is not None:
            return timestamp.astimezone(UTC).replace(tzinfo=None)
        return timestamp

    def _insert_record(
        self,
        session: Session,
        artist_key: str,
        identifier: str,
        priority: int,
    ) -> WatchlistArtist:
        now = datetime.utcnow()
        artist = self._lookup_artist(session, artist_key)
        record = WatchlistArtist(
            spotify_artist_id=identifier,
            name=(artist.name if artist else identifier),
            priority=priority,
            cooldown_s=0,
            stop_reason=None,
            retry_block_until=None,
            source_artist_id=(artist.id if artist else None),
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        session.flush()
        session.refresh(record)
        return record

    def _find_by_identifier(self, session: Session, identifier: str) -> WatchlistArtist | None:
        statement = select(WatchlistArtist).where(WatchlistArtist.spotify_artist_id == identifier)
        return session.execute(statement).scalars().first()

    def _lookup_artist(self, session: Session, artist_key: str) -> ArtistRecord | None:
        statement = select(ArtistRecord).where(ArtistRecord.artist_key == artist_key)
        return session.execute(statement).scalars().first()

    def _to_entry(self, session: Session, record: WatchlistArtist) -> WatchlistEntry:
        artist_key = self._resolve_artist_key(session, record)
        pause_reason = self._clean_reason(record.stop_reason)
        paused = bool(record.stop_reason and record.stop_reason.strip())
        resume_at = record.retry_block_until
        if resume_at is not None:
            resume_at = resume_at.replace(tzinfo=UTC)
        return WatchlistEntry(
            id=int(record.id),
            artist_key=artist_key,
            priority=int(record.priority or 0),
            paused=paused,
            pause_reason=pause_reason if paused else None,
            resume_at=resume_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _resolve_artist_key(self, session: Session, record: WatchlistArtist) -> str:
        if record.source_artist_id:
            artist = session.get(ArtistRecord, record.source_artist_id)
            if artist and artist.artist_key:
                return artist.artist_key
        identifier = (record.spotify_artist_id or "").strip()
        return f"spotify:{identifier}" if identifier else "spotify:"

    @staticmethod
    def _clean_reason(value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        return candidate or None

    @staticmethod
    def _parse_artist_key(artist_key: str) -> tuple[str, str]:
        prefix, _, identifier = artist_key.partition(":")
        source = prefix.strip().lower()
        identifier_value = identifier.strip()
        if not identifier_value:
            raise AppError(
                "artist_key must include a provider and identifier.",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            )
        if source != "spotify":
            raise AppError(
                "Only spotify:* artist keys are supported.",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
                meta={"artist_key": artist_key},
            )
        return source, identifier_value


__all__ = ["WatchlistEntry", "WatchlistService"]
