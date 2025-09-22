"""Spotify API endpoints exposed by the Harmony backend."""

from collections.abc import Sequence
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from app.core.spotify_client import SpotifyClient
from app.db import get_db
from app.models import Playlist, PlaylistItem, Song
from app.utils.logging_config import get_logger

router = APIRouter()
logger = get_logger("spotify_router")
client = SpotifyClient()


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class SongCreate(BaseModel):
    """Payload schema for songs provided when creating a playlist."""

    title: str
    artist: str
    album: str
    duration: int | None = None
    spotify_id: str | None = None


class SongOut(BaseModel):
    """Represents a song returned to the client."""

    id: int
    title: str
    artist: str
    album: str
    duration: int | None
    source: str

    class Config:
        orm_mode = True


class PlaylistCreate(BaseModel):
    """Payload schema for creating playlists including their tracks."""

    name: str
    tracks: List[SongCreate]


class PlaylistOut(BaseModel):
    """Playlist representation returned to API consumers."""

    id: int
    name: str
    songs: List[SongOut]

    class Config:
        orm_mode = True


# ---------------------------------------------------------------------------
# Database-backed endpoints
# ---------------------------------------------------------------------------


def _playlist_to_schema(playlist: Playlist) -> PlaylistOut:
    return PlaylistOut(
        id=playlist.id,
        name=playlist.name,
        songs=[SongOut.from_orm(item.song) for item in playlist.items],
    )


@router.post("/playlist", response_model=PlaylistOut)
def create_playlist(data: PlaylistCreate, db: Session = Depends(get_db)):
    """Create a Spotify playlist in the database including all songs."""

    try:
        playlist = Playlist(name=data.name)

        for index, track in enumerate(data.tracks, start=1):
            song = Song(
                title=track.title,
                artist=track.artist,
                album=track.album,
                duration=track.duration,
                source="spotify",
                spotify_id=track.spotify_id,
            )
            playlist.items.append(PlaylistItem(song=song, order=index))

        db.add(playlist)
        db.commit()

        stored_playlist = (
            db.query(Playlist)
            .options(selectinload(Playlist.items).selectinload(PlaylistItem.song))
            .filter(Playlist.id == playlist.id)
            .one()
        )

        logger.info(
            "Playlist '%s' created with %d songs", stored_playlist.name, len(data.tracks)
        )
        return _playlist_to_schema(stored_playlist)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to create playlist: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=500, detail="Fehler beim Anlegen der Playlist"
        ) from exc


@router.get("/playlists", response_model=List[PlaylistOut])
def list_playlists(db: Session = Depends(get_db)):
    """Return all stored playlists with their songs."""

    playlists: Sequence[Playlist] = (
        db.query(Playlist)
        .options(selectinload(Playlist.items).selectinload(PlaylistItem.song))
        .all()
    )
    return [_playlist_to_schema(pl) for pl in playlists]


@router.get("/songs", response_model=List[SongOut])
def list_songs(db: Session = Depends(get_db)):
    """Return all songs imported from Spotify."""

    songs: Sequence[Song] = (
        db.query(Song)
        .filter(Song.source == "spotify")
        .order_by(Song.id)
        .all()
    )
    return [SongOut.from_orm(song) for song in songs]


# ---------------------------------------------------------------------------
# Spotify client passthrough endpoints used by the prototype UI
# ---------------------------------------------------------------------------


@router.get("/playlists/metadata")
async def get_playlists_metadata() -> dict:
    """Return static playlist metadata from the in-memory Spotify client."""

    try:
        playlists = client.get_user_playlists_metadata_only()
        return {"playlists": [playlist.__dict__ for playlist in playlists]}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Playlist fetch failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/search")
async def search_tracks(query: str = Query(...)) -> dict:
    """Search the in-memory Spotify client for tracks matching the query."""

    try:
        results = client.search_tracks(query)
        return {"tracks": [track.__dict__ for track in results]}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Spotify search failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
