"""Plex API endpoints."""
from __future__ import annotations
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.core.plex_client import PlexClient
from app.db import session_scope
from app.dependencies import get_plex_client
from app.logging import get_logger
from app.models import Setting
from app.schemas import StatusResponse

logger = get_logger(__name__)

router = APIRouter()


@router.get("/status", response_model=StatusResponse)
def plex_status(client: PlexClient = Depends(get_plex_client)) -> StatusResponse:
    """Return connectivity status for the Plex client."""

    status = "connected" if client.is_connected() else "disconnected"

    artist_count: Optional[int] = None
    album_count: Optional[int] = None
    track_count: Optional[int] = None
    last_scan: Optional[datetime] = None

    with session_scope() as session:
        settings = session.execute(
            select(Setting).where(
                Setting.key.in_(
                    [
                        "plex_artist_count",
                        "plex_album_count",
                        "plex_track_count",
                        "plex_last_scan",
                    ]
                )
            )
        ).scalars()
        values = {setting.key: setting.value for setting in settings}

    def _parse_int(value: Optional[str], label: str) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            logger.warning("Invalid %s stored in settings: %s", label, value)
            return None

    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if value is None:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            logger.warning("Invalid Plex last scan timestamp stored: %s", value)
            return None

    artist_count = _parse_int(values.get("plex_artist_count"), "artist count")
    album_count = _parse_int(values.get("plex_album_count"), "album count")
    track_count = _parse_int(values.get("plex_track_count"), "track count")
    last_scan = _parse_datetime(values.get("plex_last_scan"))

    return StatusResponse(
        status=status,
        artist_count=artist_count,
        album_count=album_count,
        track_count=track_count,
        last_scan=last_scan,
    )


@router.get("/artists", response_model=list[dict[str, Any]])
def list_artists(client: PlexClient = Depends(get_plex_client)) -> List[dict[str, Any]]:
    """Return all artists known to the configured Plex library."""

    try:
        artists = client.get_all_artists()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to fetch artists from Plex: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to query Plex artists") from exc
    return artists


@router.get("/artist/{artist_id}/albums", response_model=list[dict[str, Any]])
def list_albums(
    artist_id: str, client: PlexClient = Depends(get_plex_client)
) -> List[dict[str, Any]]:
    """Return albums for a Plex artist, raising 404 if not found."""

    try:
        albums = client.get_albums_by_artist(artist_id)
    except Exception as exc:
        logger.warning("Album lookup failed for Plex artist %s: %s", artist_id, exc)
        raise HTTPException(status_code=404, detail="Artist not found") from exc
    return albums


@router.get("/album/{album_id}/tracks", response_model=list[dict[str, Any]])
def list_tracks(
    album_id: str, client: PlexClient = Depends(get_plex_client)
) -> List[dict[str, Any]]:
    """Return tracks for a Plex album, raising 404 if not found."""

    try:
        tracks = client.get_tracks_by_album(album_id)
    except Exception as exc:
        logger.warning("Track lookup failed for Plex album %s: %s", album_id, exc)
        raise HTTPException(status_code=404, detail="Album not found") from exc
    return tracks
