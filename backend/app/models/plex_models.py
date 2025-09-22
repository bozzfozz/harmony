"""SQLAlchemy models representing Plex library metadata."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlexArtist(Base):
    __tablename__ = "plex_artists"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    albums: Mapped[list["PlexAlbum"]] = relationship("PlexAlbum", back_populates="artist", cascade="all, delete-orphan")


class PlexAlbum(Base):
    __tablename__ = "plex_albums"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist_id: Mapped[str] = mapped_column(String, ForeignKey("plex_artists.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    artist: Mapped[PlexArtist] = relationship("PlexArtist", back_populates="albums")
    tracks: Mapped[list["PlexTrack"]] = relationship("PlexTrack", back_populates="album", cascade="all, delete-orphan")


class PlexTrack(Base):
    __tablename__ = "plex_tracks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    album_id: Mapped[str] = mapped_column(String, ForeignKey("plex_albums.id", ondelete="CASCADE"), nullable=False)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    album: Mapped[PlexAlbum] = relationship("PlexAlbum", back_populates="tracks")


__all__ = ["PlexArtist", "PlexAlbum", "PlexTrack"]
