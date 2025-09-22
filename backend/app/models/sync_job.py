"""Database model for synchronisation jobs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text

from app.db import Base

SYNC_STATUS = ("pending", "in_progress", "completed", "failed")


class SyncJob(Base):
    """Persist the status of a synchronisation run."""

    __tablename__ = "sync_jobs"

    id = Column(Integer, primary_key=True, index=True)
    spotify_id = Column(String, nullable=False, index=True)
    status = Column(Enum(*SYNC_STATUS, name="sync_job_status"), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    error_message = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<SyncJob id={self.id} spotify_id={self.spotify_id!r} status={self.status!r}>"
