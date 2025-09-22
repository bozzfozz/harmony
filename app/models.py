"""Database models used by the Harmony backend."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class Song(Base):
    """Represents a song stored in the local database."""

    __tablename__ = "songs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    artist = Column(String, index=True, nullable=False)
    album = Column(String, index=True, nullable=False)
    duration = Column(Integer, nullable=True)
    source = Column(String, nullable=False, default="unknown")
    plex_id = Column(String, nullable=True, unique=True)
    path = Column(String, nullable=True)

    playlist_items = relationship(
        "PlaylistItem",
        back_populates="song",
        cascade="all, delete-orphan",
    )


class Playlist(Base):
    """Represents a playlist containing multiple songs."""

    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

    items = relationship(
        "PlaylistItem",
        back_populates="playlist",
        cascade="all, delete-orphan",
        order_by="PlaylistItem.order",
    )


class PlaylistItem(Base):
    """Associative table linking playlists with their ordered songs."""

    __tablename__ = "playlist_items"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False)
    song_id = Column(Integer, ForeignKey("songs.id", ondelete="CASCADE"), nullable=False)
    order = Column(Integer, nullable=False)

    playlist = relationship("Playlist", back_populates="items")
    song = relationship("Song", back_populates="playlist_items")
