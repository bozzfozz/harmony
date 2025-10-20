"""Database models for Harmony."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)

from app.db import Base


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp for ORM defaults."""

    return datetime.now(UTC)


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
    metadata_json = Column("metadata", JSON, nullable=True)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class DownloadState(str, Enum):
    """Supported lifecycle states for a download record."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class Download(Base):
    __tablename__ = "downloads"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(1024), nullable=False)
    state = Column(String(50), nullable=False, default=DownloadState.QUEUED.value, index=True)
    progress = Column(Float, nullable=False, default=0.0)
    priority = Column(Integer, nullable=False, default=0)
    username = Column(String(255), nullable=True)
    organized_path = Column(String(2048), nullable=True)
    genre = Column(String(255), nullable=True)
    composer = Column(String(255), nullable=True)
    producer = Column(String(255), nullable=True)
    isrc = Column(String(64), nullable=True)
    copyright = Column(String(512), nullable=True)
    artwork_url = Column(String(2048), nullable=True)
    artwork_path = Column(String(2048), nullable=True)
    artwork_status = Column(String(32), nullable=False, default="pending")
    has_artwork = Column(Boolean, nullable=False, default=False)
    spotify_track_id = Column(String(128), nullable=True, index=True)
    spotify_album_id = Column(String(128), nullable=True, index=True)
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
    retry_count = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    @property
    def job_id(self) -> str | None:
        payload = self.request_payload or {}
        job_identifier = payload.get("job_id")
        if job_identifier is None:
            return None
        return str(job_identifier)

    @job_id.setter
    def job_id(self, value: str | None) -> None:
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
    timestamp = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
        index=True,
    )
    type = Column(String(128), nullable=False)
    status = Column(String(128), nullable=False)
    details = Column(JSON, nullable=True)


class ArtistPreference(Base):
    __tablename__ = "artist_preferences"

    artist_id = Column(String(128), primary_key=True)
    release_id = Column(String(128), primary_key=True)
    selected = Column(Boolean, nullable=False, default=True)


class WatchlistArtist(Base):
    __tablename__ = "watchlist_artists"
    __table_args__ = (
        Index(
            "ix_watchlist_artists_spotify_artist_id",
            "spotify_artist_id",
            unique=True,
        ),
        Index(
            "ix_watchlist_artists_source_artist_id",
            "source_artist_id",
            unique=True,
        ),
        Index(
            "ix_watchlist_artists_priority_last_scan",
            "priority",
            "last_scan_at",
            "id",
        ),
        Index("ix_watchlist_artists_stop_reason", "stop_reason"),
        Index("ix_watchlist_artists_retry_budget_left", "retry_budget_left"),
    )

    id = Column(Integer, primary_key=True, index=True)
    spotify_artist_id = Column(String(128), nullable=False)
    name = Column(String(512), nullable=False)
    last_checked = Column(DateTime, nullable=True)
    retry_block_until = Column(DateTime, nullable=True)
    source_artist_id = Column(Integer, nullable=True)
    priority = Column(Integer, nullable=False, default=0, server_default=text("0"))
    cooldown_s = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_scan_at = Column(DateTime, nullable=True)
    last_hash = Column(String(128), nullable=True)
    retry_budget_left = Column(Integer, nullable=True)
    stop_reason = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ArtistKnownReleaseRecord(Base):
    __tablename__ = "artist_known_releases"
    __table_args__ = (
        Index(
            "ix_artist_known_releases_artist_track",
            "artist_id",
            "track_id",
            unique=True,
        ),
        Index("ix_artist_known_releases_artist_id", "artist_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    artist_id = Column(
        Integer, ForeignKey("watchlist_artists.id", ondelete="CASCADE"), nullable=False
    )
    track_id = Column(String(128), nullable=False)
    etag = Column(String(255), nullable=True)
    fetched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ArtistRecord(Base):
    __tablename__ = "artists"
    __table_args__ = (
        Index("ix_artists_artist_key", "artist_key", unique=True),
        Index("ix_artists_updated_at", "updated_at"),
        Index("uq_artists_source_source_id", "source", "source_id", unique=True),
    )

    id = Column(Integer, primary_key=True, index=True)
    artist_key = Column(String(255), nullable=False)
    source = Column(String(50), nullable=False)
    source_id = Column(String(255), nullable=True)
    name = Column(String(512), nullable=False)
    genres = Column(JSON, nullable=False, default=list)
    images = Column(JSON, nullable=False, default=list)
    popularity = Column(Integer, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)
    etag = Column(String(64), nullable=False)
    version = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ArtistReleaseRecord(Base):
    __tablename__ = "artist_releases"
    __table_args__ = (
        Index("uq_artist_releases_source_source_id", "source", "source_id", unique=True),
        Index("ix_artist_releases_artist_id", "artist_id"),
        Index("ix_artist_releases_artist_key", "artist_key"),
        Index("ix_artist_releases_release_date", "release_date"),
        Index("ix_artist_releases_updated_at", "updated_at"),
        Index("ix_artist_releases_inactive_at", "inactive_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    artist_id = Column(Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False)
    artist_key = Column(String(255), nullable=False)
    source = Column(String(50), nullable=False)
    source_id = Column(String(255), nullable=True)
    title = Column(String(512), nullable=False)
    release_date = Column(Date, nullable=True)
    release_type = Column(String(50), nullable=True)
    total_tracks = Column(Integer, nullable=True)
    version = Column(String(64), nullable=True)
    etag = Column(String(64), nullable=False)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    inactive_at = Column(DateTime, nullable=True)
    inactive_reason = Column(Text, nullable=True)


class ArtistAuditRecord(Base):
    __tablename__ = "artist_audit"
    __table_args__ = (
        Index("ix_artist_audit_artist_key", "artist_key"),
        Index("ix_artist_audit_event", "event"),
        Index("ix_artist_audit_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    job_id = Column(String(64), nullable=True)
    artist_key = Column(String(255), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(255), nullable=True)
    event = Column(String(32), nullable=False)
    before_json = Column("before", JSON, nullable=True)
    after_json = Column("after", JSON, nullable=True)


class ArtistWatchlistEntry(Base):
    __tablename__ = "artist_watchlist"
    __table_args__ = (Index("ix_artist_watchlist_priority", "priority", "last_enqueued_at"),)

    artist_key = Column(String(255), primary_key=True)
    priority = Column(Integer, nullable=False, default=0)
    last_enqueued_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    cooldown_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ImportSession(Base):
    __tablename__ = "import_sessions"
    __table_args__ = (CheckConstraint("mode IN ('FREE','PRO')", name="ck_import_sessions_mode"),)

    id = Column(String(64), primary_key=True)
    mode = Column(String(10), nullable=False)
    state = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    totals_json = Column(Text, nullable=True)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        Index(
            "ix_import_batches_session_playlist",
            "session_id",
            "playlist_id",
            unique=True,
        ),
    )

    id = Column(String(64), primary_key=True)
    session_id = Column(String(64), ForeignKey("import_sessions.id"), nullable=False, index=True)
    playlist_id = Column(String(128), nullable=False, index=True)
    offset = Column(Integer, nullable=False, default=0)
    limit = Column(Integer, nullable=True)
    state = Column(String(32), nullable=False, default="pending")


class WorkerJob(Base):
    __tablename__ = "worker_jobs"
    __table_args__ = (
        Index(
            "ix_worker_jobs_worker_state_scheduled",
            "worker",
            "state",
            "scheduled_at",
        ),
        Index("ix_worker_jobs_worker_job_key", "worker", "job_key"),
        Index("ix_worker_jobs_worker_lease", "worker", "lease_expires_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    worker = Column(String(64), index=True, nullable=False)
    payload = Column(JSON, nullable=False)
    state = Column(String(32), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    scheduled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    visibility_timeout = Column(Integer, nullable=False, default=0)
    lease_expires_at = Column(DateTime, nullable=True)
    job_key = Column(String(128), nullable=True)
    stop_reason = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class QueueJobStatus(str, Enum):
    """Lifecycle states for general purpose queue jobs."""

    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QueueJob(Base):
    __tablename__ = "queue_jobs"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="ck_queue_jobs_priority_non_negative"),
        CheckConstraint("attempts >= 0", name="ck_queue_jobs_attempts_non_negative"),
        CheckConstraint(
            "status IN ('pending','leased','completed','failed','cancelled')",
            name="ck_queue_jobs_status_valid",
        ),
        Index(
            "ix_queue_jobs_type_status_available_at",
            "type",
            "status",
            "available_at",
        ),
        Index("ix_queue_jobs_lease_expires_at", "lease_expires_at"),
        Index(
            "ix_queue_jobs_idempotency_key_not_null",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(64), nullable=False, index=True)
    status = Column(
        String(32),
        nullable=False,
        default=QueueJobStatus.PENDING.value,
        index=True,
    )
    payload = Column("payload_json", JSON, nullable=False, default=dict)
    priority = Column(Integer, nullable=False, default=0)
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    idempotency_key = Column(String(128), nullable=True)
    last_error = Column(Text, nullable=True)
    stop_reason = Column(String(64), nullable=True)
    result_payload = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class AutoSyncSkippedTrack(Base):
    __tablename__ = "auto_sync_skipped_tracks"

    id = Column(Integer, primary_key=True, index=True)
    track_key = Column(String(512), unique=True, nullable=False)
    spotify_id = Column(String(128), nullable=True)
    failure_reason = Column(String(128), nullable=False, default="unknown")
    failure_count = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class IngestJobState(str, Enum):
    """Lifecycle states shared across ingest job implementations."""

    REGISTERED = "registered"
    NORMALIZED = "normalized"
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestItemState(str, Enum):
    """Lifecycle states for individual ingest items."""

    REGISTERED = "registered"
    NORMALIZED = "normalized"
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id = Column(String(64), primary_key=True)
    source = Column(String(16), nullable=False, default="FREE")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    state = Column(
        String(32),
        nullable=False,
        default=IngestJobState.REGISTERED.value,
        index=True,
    )
    skipped_playlists = Column(Integer, nullable=False, default=0)
    skipped_tracks = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)


class IngestItem(Base):
    __tablename__ = "ingest_items"
    __table_args__ = (
        Index("ix_ingest_items_job_state", "job_id", "state"),
        Index("ix_ingest_items_job_hash", "job_id", "dedupe_hash"),
    )

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(64), ForeignKey("ingest_jobs.id"), nullable=False, index=True)
    source_type = Column(String(32), nullable=False)
    playlist_url = Column(String(2048), nullable=True)
    raw_line = Column(Text, nullable=True)
    artist = Column(String(512), nullable=True)
    title = Column(String(512), nullable=True)
    album = Column(String(512), nullable=True)
    duration_sec = Column(Integer, nullable=True)
    spotify_track_id = Column(String(128), nullable=True, index=True)
    spotify_album_id = Column(String(128), nullable=True, index=True)
    isrc = Column(String(64), nullable=True)
    dedupe_hash = Column(String(64), nullable=False, index=True)
    source_fingerprint = Column(String(64), nullable=False, index=True)
    state = Column(
        String(32),
        nullable=False,
        default=IngestItemState.REGISTERED.value,
        index=True,
    )
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class BackfillJob(Base):
    __tablename__ = "backfill_jobs"
    __table_args__ = (
        Index("ix_backfill_jobs_state", "state"),
        Index("ix_backfill_jobs_created_at", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    state = Column(String(32), nullable=False, default="queued")
    requested_items = Column(Integer, nullable=False, default=0)
    processed_items = Column(Integer, nullable=False, default=0)
    matched_items = Column(Integer, nullable=False, default=0)
    cache_hits = Column(Integer, nullable=False, default=0)
    cache_misses = Column(Integer, nullable=False, default=0)
    expanded_playlists = Column(Integer, nullable=False, default=0)
    expanded_tracks = Column(Integer, nullable=False, default=0)
    expand_playlists = Column(Boolean, nullable=False, default=False)
    include_cached_results = Column(Boolean, nullable=True, default=True)
    duration_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class SpotifyCache(Base):
    __tablename__ = "spotify_cache"

    key = Column(String(512), primary_key=True)
    track_id = Column(String(128), nullable=True)
    album_id = Column(String(128), nullable=True)
    expires_at = Column(DateTime, nullable=False)
