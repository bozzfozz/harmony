from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base


class Song(Base):
    __tablename__ = "songs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    artist = Column(String, index=True)
    album = Column(String, index=True)
    duration = Column(Integer, nullable=True)
    path = Column(String, nullable=True)
    source = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    playlist_items = relationship(
        "PlaylistItem",
        back_populates="song",
        cascade="all, delete",
        passive_deletes=True,
    )


class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship(
        "PlaylistItem",
        back_populates="playlist",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PlaylistItem(Base):
    __tablename__ = "playlist_items"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(
        Integer,
        ForeignKey("playlists.id", ondelete="CASCADE"),
        nullable=False,
    )
    song_id = Column(
        Integer,
        ForeignKey("songs.id", ondelete="CASCADE"),
        nullable=False,
    )
    order = Column(Integer, nullable=True)

    playlist = relationship("Playlist", back_populates="items")
    song = relationship("Song", back_populates="playlist_items")


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Download(Base):
    __tablename__ = "downloads"

    id = Column(Integer, primary_key=True, index=True)
    song_id = Column(Integer, ForeignKey("songs.id", ondelete="SET NULL"), nullable=True)
    source = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    status = Column(String, default="pending")
    progress = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    song = relationship("Song")


class MatchResult(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    spotify_track_id = Column(String, index=True)
    plex_track_id = Column(String, index=True)
    confidence = Column(Integer, default=0)
    match_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
