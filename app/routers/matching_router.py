"""Matching endpoints for Harmony."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.matching_engine import MusicMatchingEngine
from app.dependencies import get_db, get_matching_engine
from app.logging import get_logger
from app.models import Match
from app.schemas import AlbumMatchingRequest, MatchingRequest, MatchingResponse

logger = get_logger(__name__)

router = APIRouter()


def _extract_target_id(candidate: Optional[Dict[str, Any]]) -> Optional[str]:
    if not candidate:
        return None
    for key in ("id", "ratingKey", "filename"):
        value = candidate.get(key)
        if value is not None:
            return str(value)
    return None


def _persist_match(session: Session, match: Match) -> None:
    """Persist a match, rolling back on failure."""

    try:
        session.add(match)
        session.commit()
    except Exception as exc:  # pragma: no cover - database failure is exceptional
        session.rollback()
        logger.error("Failed to persist match %s: %s", match, exc)
        raise HTTPException(status_code=500, detail="Failed to store match result") from exc


@router.post("/spotify-to-plex", response_model=MatchingResponse)
def spotify_to_plex(
    payload: MatchingRequest,
    engine: MusicMatchingEngine = Depends(get_matching_engine),
    session: Session = Depends(get_db),
) -> MatchingResponse:
    """Match a Spotify track against Plex candidates and persist the result."""

    best_match, confidence = engine.find_best_match(payload.spotify_track, payload.candidates)
    target_id = _extract_target_id(best_match)
    match = Match(
        source="spotify-to-plex",
        spotify_track_id=str(payload.spotify_track.get("id")),
        target_id=target_id,
        confidence=confidence,
    )
    _persist_match(session, match)
    return MatchingResponse(best_match=best_match, confidence=confidence)


@router.post("/spotify-to-soulseek", response_model=MatchingResponse)
def spotify_to_soulseek(
    payload: MatchingRequest,
    engine: MusicMatchingEngine = Depends(get_matching_engine),
    session: Session = Depends(get_db),
) -> MatchingResponse:
    """Match a Spotify track against Soulseek candidates and persist the result."""

    best_candidate: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for candidate in payload.candidates:
        score = engine.calculate_slskd_match_confidence(payload.spotify_track, candidate)
        if score > best_score:
            best_score = score
            best_candidate = candidate
    target_id = _extract_target_id(best_candidate)
    match = Match(
        source="spotify-to-soulseek",
        spotify_track_id=str(payload.spotify_track.get("id")),
        target_id=target_id,
        confidence=best_score,
    )
    _persist_match(session, match)
    return MatchingResponse(best_match=best_candidate, confidence=best_score)


@router.post("/spotify-to-plex-album", response_model=MatchingResponse)
def spotify_to_plex_album(
    payload: AlbumMatchingRequest, engine: MusicMatchingEngine = Depends(get_matching_engine)
) -> MatchingResponse:
    """Return the best matching Plex album for the provided Spotify album."""

    best_match, confidence = engine.find_best_album_match(payload.spotify_album, payload.candidates)
    return MatchingResponse(best_match=best_match, confidence=confidence)
