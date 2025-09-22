"""Endpoints exposing Spotify/Plex/Soulseek matching functionality."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.utils.logging_config import get_logger
from backend.app.core.matching_engine import (
    MusicMatchingEngine,
    PlexTrackInfo,
    SoulseekTrackResult,
    SpotifyTrack,
)
from backend.app.core.spotify_client import SpotifyClient
from backend.app.models.matching_models import MatchHistory
from backend.app.models.plex_models import PlexAlbum, PlexArtist, PlexTrack


logger = get_logger("matching_router")


class SpotifyToPlexRequest(BaseModel):
    spotify_track_id: str = Field(..., min_length=1)
    plex_artist_id: str = Field(..., min_length=1)


class SoulseekResultPayload(BaseModel):
    id: str | None = None
    title: str
    artist: str | None = None
    filename: str
    duration_ms: int | None = Field(default=None, ge=0)
    bitrate: int | None = Field(default=None, ge=0)

    @field_validator("title", "filename")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value


class SpotifyToSoulseekRequest(BaseModel):
    spotify_track_id: str = Field(..., min_length=1)
    results: List[SoulseekResultPayload]


class MatchResponse(BaseModel):
    source: str
    spotify_track_id: str
    target_id: str | None
    target_title: str | None
    target_artist: str | None
    confidence: float
    matched: bool


router = APIRouter(prefix="/matching", tags=["Matching"])

spotify_client = SpotifyClient()
matching_engine = MusicMatchingEngine()


def _load_spotify_track(spotify_track_id: str) -> SpotifyTrack:
    details = spotify_client.get_track_details(spotify_track_id)
    if not details:
        raise HTTPException(status_code=404, detail="Spotify track not found")
    album = details.get("album") or {}
    if not isinstance(album, dict):
        album = {}
    return SpotifyTrack(
        id=details.get("id", spotify_track_id),
        name=details.get("name", ""),
        artists=list(details.get("artists", [])),
        album=album.get("name"),
        duration_ms=details.get("duration_ms"),
    )


def _store_history(db: Session, source: str, spotify_track_id: str, target_id: str, confidence: float) -> None:
    history = MatchHistory(
        source=source,
        spotify_track_id=spotify_track_id,
        target_id=target_id,
        confidence=confidence,
    )
    db.add(history)
    db.commit()


@router.post("/spotify-to-plex", response_model=MatchResponse)
def match_spotify_to_plex(payload: SpotifyToPlexRequest, db: Session = Depends(get_db)) -> MatchResponse:
    artist = db.get(PlexArtist, payload.plex_artist_id)
    if artist is None:
        logger.warning("Plex artist %s not found", payload.plex_artist_id)
        raise HTTPException(status_code=404, detail="Plex artist not found")

    tracks_with_albums = (
        db.query(PlexTrack, PlexAlbum)
        .join(PlexAlbum, PlexTrack.album_id == PlexAlbum.id)
        .filter(PlexAlbum.artist_id == payload.plex_artist_id)
        .all()
    )

    if not tracks_with_albums:
        logger.warning("No Plex tracks stored for artist %s", payload.plex_artist_id)
        raise HTTPException(status_code=404, detail="No Plex tracks for artist")

    spotify_track = _load_spotify_track(payload.spotify_track_id)
    plex_tracks = [
        PlexTrackInfo(
            id=track.id,
            title=track.title,
            artist=artist.name,
            album=album.title,
            duration_ms=track.duration,
        )
        for track, album in tracks_with_albums
    ]

    result = matching_engine.find_best_match(spotify_track, plex_tracks)
    best_track = result.get("track")
    confidence = float(result.get("confidence", 0.0))
    matched = bool(result.get("matched")) and best_track is not None

    if matched:
        _store_history(db, "plex", spotify_track.id, best_track.id, confidence)

    return MatchResponse(
        source="plex",
        spotify_track_id=spotify_track.id,
        target_id=getattr(best_track, "id", None),
        target_title=getattr(best_track, "title", None),
        target_artist=getattr(best_track, "artist", None),
        confidence=confidence,
        matched=matched,
    )


@router.post("/spotify-to-soulseek", response_model=MatchResponse)
def match_spotify_to_soulseek(
    payload: SpotifyToSoulseekRequest, db: Session = Depends(get_db)
) -> MatchResponse:
    if not payload.results:
        raise HTTPException(status_code=400, detail="No Soulseek results provided")

    spotify_track = _load_spotify_track(payload.spotify_track_id)
    soulseek_results = [
        SoulseekTrackResult(
            id=item.id,
            title=item.title,
            artist=item.artist,
            filename=item.filename,
            duration_ms=item.duration_ms,
            bitrate=item.bitrate,
        )
        for item in payload.results
    ]

    best_result = None
    best_confidence = 0.0
    for result in soulseek_results:
        confidence = matching_engine.calculate_slskd_match_confidence(spotify_track, result)
        if confidence > best_confidence:
            best_confidence = confidence
            best_result = result

    matched = best_result is not None and best_confidence >= 0.5

    target_id = None
    target_title = None
    target_artist = None
    if matched and best_result is not None:
        target_id = best_result.id or best_result.filename
        target_title = best_result.title
        target_artist = best_result.artist
        _store_history(db, "soulseek", spotify_track.id, target_id, best_confidence)

    return MatchResponse(
        source="soulseek",
        spotify_track_id=spotify_track.id,
        target_id=target_id,
        target_title=target_title,
        target_artist=target_artist,
        confidence=best_confidence,
        matched=matched,
    )


__all__ = ["router"]

