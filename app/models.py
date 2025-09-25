"""Database models for Harmony."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text

# JSON is optional depending on database backend; fall back to Text if unavailable
try:  # pragma: no cover - fallback handling
    from sqlalchemy import JSON
except ImportError:  # pragma: no cover - compatibility
    JSON = Text  # type: ignore

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(String(128), primary_key=True)
    name = Column(String(512), nullable=False)
    track_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Download(Base):
    __tablename__ = "downloads"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(1024), nullable=False)
    state = Column(String(50), nullable=False, default="queued", index=True)
    progress = Column(Float, nullable=False, default=0.0)
    priority = Column(Integer, nullable=False, default=0)
    username = Column(String(255), nullable=True)
    genre = Column(String(255), nullable=True)
    composer = Column(String(255), nullable=True)
    producer = Column(String(255), nullable=True)
    isrc = Column(String(64), nullable=True)
    copyright = Column(String(512), nullable=True)
    artwork_url = Column(String(2048), nullable=True)
    artwork_path = Column(String(2048), nullable=True)
    artwork_status = Column(String(32), nullable=False, default="pending")
    lyrics_path = Column(String(2048), nullable=True)
    lyrics_status = Column(String(32), nullable=False, default="pending")
    has_lyrics = Column(Boolean, nullable=False, default=False)
    request_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    @property
    def job_id(self) -> Optional[str]:
        payload = self.request_payload or {}
        job_identifier = payload.get("job_id")
        if job_identifier is None:
            return None
        return str(job_identifier)

    @job_id.setter
    def job_id(self, value: Optional[str]) -> None:
        payload = dict(self.request_payload or {})
        if value is None:
            payload.pop("job_id", None)
        else:
            payload["job_id"] = str(value)
        self.request_payload = payload


class DiscographyJob(Base):
    __tablename__ = "discography_jobs"

    id = Column(Integer, primary_key=True, index=True)
    artist_id = Column(String(128), nullable=False, index=True)
    artist_name = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50), nullable=False)
    spotify_track_id = Column(String(128), index=True, nullable=False)
    target_id = Column(String(128), nullable=True)
    context_id = Column(String(128), nullable=True)
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SettingHistory(Base):
    __tablename__ = "settings_history"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (
        Index(
            "ix_activity_events_type_status_timestamp",
            "type",
            "status",
            "timestamp",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    type = Column(String(128), nullable=False)
    status = Column(String(128), nullable=False)
    details = Column(JSON, nullable=True)


class ArtistPreference(Base):
    __tablename__ = "artist_preferences"

    artist_id = Column(String(128), primary_key=True)
    release_id = Column(String(128), primary_key=True)
    selected = Column(Boolean, nullable=False, default=True)


class WorkerJob(Base):
    __tablename__ = "worker_jobs"

    id = Column(Integer, primary_key=True, index=True)
    worker = Column(String(64), index=True, nullable=False)
    payload = Column(JSON, nullable=False)
    state = Column(String(32), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    scheduled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class AutoSyncSkippedTrack(Base):
    __tablename__ = "auto_sync_skipped_tracks"

    id = Column(Integer, primary_key=True, index=True)
    track_key = Column(String(512), unique=True, nullable=False)
    spotify_id = Column(String(128), nullable=True)
    failure_reason = Column(String(128), nullable=False, default="unknown")
    failure_count = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime, default=datetime.utcnow, nullable=False)
