from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.orm import Session

from app.db import Base, session_scope


@dataclass(frozen=True)
class StoredUiSession:
    identifier: str
    role: str
    fingerprint: str
    issued_at: datetime
    last_seen_at: datetime
    feature_spotify: bool
    feature_soulseek: bool
    feature_dlq: bool
    feature_imports: bool
    spotify_free_ingest_job_id: str | None = None
    spotify_backfill_job_id: str | None = None


class UiSessionRecord(Base):
    __tablename__ = "ui_sessions"

    identifier = Column(String(128), primary_key=True)
    role = Column(String(32), nullable=False)
    fingerprint = Column(String(128), nullable=False, index=True)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    feature_spotify = Column(Boolean, nullable=False, default=False)
    feature_soulseek = Column(Boolean, nullable=False, default=False)
    feature_dlq = Column(Boolean, nullable=False, default=False)
    feature_imports = Column(Boolean, nullable=False, default=False)
    spotify_free_ingest_job_id = Column(String(255), nullable=True)
    spotify_backfill_job_id = Column(String(255), nullable=True)


SessionFactory = Callable[[], AbstractContextManager[Session]]


class UiSessionStore:
    def __init__(self, *, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory or session_scope

    def create_session(self, session: StoredUiSession) -> None:
        record = UiSessionRecord(
            identifier=session.identifier,
            role=session.role,
            fingerprint=session.fingerprint,
            issued_at=session.issued_at,
            last_seen_at=session.last_seen_at,
            feature_spotify=session.feature_spotify,
            feature_soulseek=session.feature_soulseek,
            feature_dlq=session.feature_dlq,
            feature_imports=session.feature_imports,
            spotify_free_ingest_job_id=session.spotify_free_ingest_job_id,
            spotify_backfill_job_id=session.spotify_backfill_job_id,
        )
        with self._session_factory() as db_session:
            db_session.merge(record)

    def get_session(self, identifier: str) -> StoredUiSession | None:
        with self._session_factory() as db_session:
            record = db_session.get(UiSessionRecord, identifier)
            if record is None:
                return None
            return self._record_to_stored(record)

    def delete_session(self, identifier: str) -> StoredUiSession | None:
        with self._session_factory() as db_session:
            record = db_session.get(UiSessionRecord, identifier)
            if record is None:
                return None
            stored = self._record_to_stored(record)
            db_session.delete(record)
            return stored

    def update_last_seen(self, identifier: str, timestamp: datetime) -> bool:
        with self._session_factory() as db_session:
            record = db_session.get(UiSessionRecord, identifier)
            if record is None:
                return False
            record.last_seen_at = timestamp
            return True

    def set_spotify_free_ingest_job_id(self, identifier: str, job_id: str | None) -> bool:
        return self._update_job_fields(
            identifier,
            spotify_free_ingest_job_id=job_id,
        )

    def set_spotify_backfill_job_id(self, identifier: str, job_id: str | None) -> bool:
        return self._update_job_fields(
            identifier,
            spotify_backfill_job_id=job_id,
        )

    def clear_job_state(self, identifier: str) -> bool:
        return self._update_job_fields(
            identifier,
            spotify_free_ingest_job_id=None,
            spotify_backfill_job_id=None,
        )

    def _update_job_fields(self, identifier: str, **fields: str | None) -> bool:
        with self._session_factory() as db_session:
            record = db_session.get(UiSessionRecord, identifier)
            if record is None:
                return False
            for key, value in fields.items():
                setattr(record, key, value)
            return True

    @staticmethod
    def _record_to_stored(record: UiSessionRecord) -> StoredUiSession:
        return StoredUiSession(
            identifier=record.identifier,
            role=record.role,
            fingerprint=record.fingerprint,
            issued_at=_as_utc(record.issued_at),
            last_seen_at=_as_utc(record.last_seen_at),
            feature_spotify=bool(record.feature_spotify),
            feature_soulseek=bool(record.feature_soulseek),
            feature_dlq=bool(record.feature_dlq),
            feature_imports=bool(record.feature_imports),
            spotify_free_ingest_job_id=record.spotify_free_ingest_job_id,
            spotify_backfill_job_id=record.spotify_backfill_job_id,
        )


__all__ = [
    "StoredUiSession",
    "UiSessionStore",
    "UiSessionRecord",
]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
