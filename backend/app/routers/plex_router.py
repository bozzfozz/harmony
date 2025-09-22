"""Plex API endpoints backed by the persistent database."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.utils.logging_config import get_logger
from backend.app.core.plex_client import PlexClient
from backend.app.models.plex_models import PlexAlbum, PlexArtist, PlexTrack

logger = get_logger("plex_router")

router = APIRouter(prefix="/plex", tags=["Plex"])

plex_client = PlexClient()


def _serialise_artist(artist: PlexArtist) -> dict[str, Any]:
    return {"id": artist.id, "name": artist.name}


def _serialise_album(album: PlexAlbum) -> dict[str, Any]:
    return {"id": album.id, "title": album.title, "artist_id": album.artist_id}


def _serialise_track(track: PlexTrack) -> dict[str, Any]:
    return {
        "id": track.id,
        "title": track.title,
        "album_id": track.album_id,
        "duration": track.duration,
    }


@router.get("/status")
def plex_status() -> dict[str, bool]:
    """Return the connectivity status of the Plex client."""

    try:
        connected = plex_client.is_connected()
    except Exception as exc:  # pragma: no cover - defensive safety net
        logger.error("Plex status check failed: %s", exc)
        raise HTTPException(status_code=503, detail="Unable to determine Plex status") from exc

    return {"connected": connected}


@router.get("/artists")
def get_artists(db: Session = Depends(get_db)) -> dict[str, list[dict[str, Any]]]:
    """List all artists stored in the local Plex cache."""

    artists = db.query(PlexArtist).order_by(PlexArtist.name.asc()).all()
    logger.info("Returned %s Plex artists", len(artists))
    return {"artists": [_serialise_artist(artist) for artist in artists]}


@router.get("/albums/{artist_id}")
def get_albums(artist_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """List albums for a given artist."""

    artist = db.get(PlexArtist, artist_id)
    if artist is None:
        logger.warning("Requested albums for unknown artist %s", artist_id)
        raise HTTPException(status_code=404, detail="Artist not found")

    albums = (
        db.query(PlexAlbum)
        .filter(PlexAlbum.artist_id == artist_id)
        .order_by(PlexAlbum.title.asc())
        .all()
    )
    logger.info("Returned %s Plex albums for artist %s", len(albums), artist_id)
    return {"artist": _serialise_artist(artist), "albums": [_serialise_album(album) for album in albums]}


@router.get("/tracks/{album_id}")
def get_tracks(album_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """List tracks for a given album."""

    album = db.get(PlexAlbum, album_id)
    if album is None:
        logger.warning("Requested tracks for unknown album %s", album_id)
        raise HTTPException(status_code=404, detail="Album not found")

    tracks = (
        db.query(PlexTrack)
        .filter(PlexTrack.album_id == album_id)
        .order_by(PlexTrack.title.asc())
        .all()
    )
    logger.info("Returned %s Plex tracks for album %s", len(tracks), album_id)
    return {
        "album": _serialise_album(album),
        "tracks": [_serialise_track(track) for track in tracks],
    }
