from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.matching_engine import MatchResult, MusicMatchingEngine
from app.core.plex_client import PlexClient
from app.core.spotify_client import Album, SpotifyClient, Track
from app.utils.logging_config import get_logger

logger = get_logger("matching_router")
router = APIRouter()
engine = MusicMatchingEngine()
spotify_client = SpotifyClient()
plex_client = PlexClient()


class TrackMatch(BaseModel):
    spotify_title: str
    spotify_artists: List[str]
    plex_title: str
    plex_artist: str
    confidence: float
    match_type: str
    is_match: bool


class AlbumMatch(BaseModel):
    spotify_album: str
    spotify_artist: str
    plex_album: str
    plex_artist: str
    confidence: float


@router.get("/track", response_model=TrackMatch)
async def match_track(spotify_track_id: str = Query(..., min_length=5)) -> TrackMatch:
    """Match a Spotify track to the best Plex library candidate."""

    try:
        if not spotify_client.is_authenticated():
            raise HTTPException(status_code=401, detail="Spotify not authenticated")

        spotify_track = spotify_client.get_track_details(spotify_track_id)
        if not spotify_track:
            raise HTTPException(status_code=404, detail="Spotify track not found")

        candidates = plex_client.search_tracks(spotify_track["name"])
        if not candidates:
            raise HTTPException(status_code=404, detail="No Plex candidates found")

        result: MatchResult = engine.find_best_match(
            Track.from_spotify_track(spotify_track["raw_data"]),
            candidates,
        )

        return TrackMatch(
            spotify_title=spotify_track["name"],
            spotify_artists=spotify_track["artists"],
            plex_title=result.plex_track.title if result.plex_track else "",
            plex_artist=result.plex_track.artist if result.plex_track else "",
            confidence=result.confidence,
            match_type=result.match_type,
            is_match=result.is_match,
        )

    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Track matching failed: %s", exc, exc_info=exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/album", response_model=AlbumMatch)
async def match_album(spotify_album_id: str = Query(..., min_length=5)) -> AlbumMatch:
    """Match a Spotify album to Plex album metadata."""

    try:
        if not spotify_client.is_authenticated():
            raise HTTPException(status_code=401, detail="Spotify not authenticated")

        spotify_album = spotify_client.get_album(spotify_album_id)
        if not spotify_album:
            raise HTTPException(status_code=404, detail="Spotify album not found")

        plex_albums = plex_client.search_albums(spotify_album["name"])
        if not plex_albums:
            raise HTTPException(status_code=404, detail="No Plex albums found")

        best_match, confidence = engine.find_best_album_match(
            Album.from_spotify_album(spotify_album),
            [album.__dict__ for album in plex_albums],
        )

        if not best_match:
            raise HTTPException(status_code=404, detail="No confident match found")

        return AlbumMatch(
            spotify_album=spotify_album["name"],
            spotify_artist=spotify_album["artists"][0]["name"],
            plex_album=str(best_match.get("title", "")),
            plex_artist=str(best_match.get("artist", "")),
            confidence=confidence,
        )

    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Album matching failed: %s", exc, exc_info=exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
