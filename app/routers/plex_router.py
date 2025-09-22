from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Playlist, PlaylistItem, Song
from app.utils.logging_config import get_logger

router = APIRouter()
logger = get_logger("plex_router")


# -------------------------
# Pydantic Schemas
# -------------------------


class PlexSongCreate(BaseModel):
    title: str
    artist: str
    album: str
    duration: int | None = None
    plex_id: str | None = None


class PlexSongOut(BaseModel):
    id: int
    title: str
    artist: str
    album: str
    duration: int | None
    source: str

    class Config:
        orm_mode = True


class PlexPlaylistCreate(BaseModel):
    name: str
    tracks: List[PlexSongCreate]


class PlexPlaylistOut(BaseModel):
    id: int
    name: str
    songs: List[PlexSongOut]

    class Config:
        orm_mode = True


# -------------------------
# Endpoints
# -------------------------


@router.post("/playlist", response_model=PlexPlaylistOut)
def create_playlist(data: PlexPlaylistCreate, db: Session = Depends(get_db)) -> PlexPlaylistOut:
    """Create a new Plex playlist along with its songs."""

    try:
        playlist = Playlist(name=data.name)
        db.add(playlist)
        db.flush()  # Ensure the playlist has an ID for the relationship mappings

        for idx, track in enumerate(data.tracks, start=1):
            song = Song(
                title=track.title,
                artist=track.artist,
                album=track.album,
                duration=track.duration,
                source="plex",
                plex_id=track.plex_id,
            )
            db.add(song)
            db.flush()

            item = PlaylistItem(order=idx)
            item.song = song
            playlist.items.append(item)

        db.commit()
        db.refresh(playlist)

        logger.info("Created Plex playlist '%s' with %d songs", playlist.name, len(data.tracks))
        return PlexPlaylistOut(
            id=playlist.id,
            name=playlist.name,
            songs=[PlexSongOut.from_orm(item.song) for item in playlist.items],
        )

    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to create Plex playlist: %s", exc)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create playlist") from exc


@router.get("/playlists", response_model=List[PlexPlaylistOut])
def list_playlists(db: Session = Depends(get_db)) -> List[PlexPlaylistOut]:
    """Return all stored Plex playlists."""

    playlists = db.query(Playlist).all()
    result: List[PlexPlaylistOut] = []
    for playlist in playlists:
        result.append(
            PlexPlaylistOut(
                id=playlist.id,
                name=playlist.name,
                songs=[PlexSongOut.from_orm(item.song) for item in playlist.items],
            )
        )
    return result


@router.get("/songs", response_model=List[PlexSongOut])
def list_songs(db: Session = Depends(get_db)) -> List[PlexSongOut]:
    """Return all songs sourced from Plex."""

    songs = db.query(Song).filter(Song.source == "plex").all()
    return [PlexSongOut.from_orm(song) for song in songs]
