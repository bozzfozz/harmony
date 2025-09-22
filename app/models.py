"""SQLAlchemy models used by the Harmony backend."""

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class Song(Base):
    """Represents an individual song stored in the database."""

    __tablename__ = "songs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    artist = Column(String, index=True, nullable=False)
    album = Column(String, index=True, nullable=False)
    duration = Column(Integer, nullable=True)
    source = Column(String, index=True, nullable=False, default="local")
    spotify_id = Column(String, unique=True, nullable=True)

    playlist_items = relationship(
        "PlaylistItem", back_populates="song", cascade="all, delete-orphan"
    )


class Playlist(Base):
    """A collection of songs grouped under a user-defined playlist."""

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
    """Association table storing the order of songs within a playlist."""

    __tablename__ = "playlist_items"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id"), nullable=False)
    song_id = Column(Integer, ForeignKey("songs.id"), nullable=False)
    order = Column(Integer, nullable=False)

    playlist = relationship("Playlist", back_populates="items")
    song = relationship("Song", back_populates="playlist_items")
