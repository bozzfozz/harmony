"""Matching endpoints for Harmony."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.matching_engine import MusicMatchingEngine
from app.dependencies import get_db, get_matching_engine
from app.integrations.normalizers import normalize_slskd_candidate, normalize_spotify_track
from app.logging import get_logger
from app.models import Download, Match
from app.schemas import MatchingRequest, MatchingResponse

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


def _attach_download_metadata(
    best_match: Optional[Dict[str, Any]], session: Session
) -> Optional[Dict[str, Any]]:
    if not best_match:
        return best_match

    for key in ("download_id", "id"):
        identifier = best_match.get(key)
        try:
            download_id = int(identifier)
        except (TypeError, ValueError):
            continue
        download = session.get(Download, download_id)
        if download is None:
            continue
        enriched = dict(best_match)
        metadata_payload: Dict[str, Any] = {}
        if isinstance(enriched.get("metadata"), dict):
            metadata_payload = dict(enriched["metadata"])
        for field in ("genre", "composer", "producer", "isrc"):
            value = getattr(download, field)
            if value and field not in metadata_payload:
                metadata_payload[field] = value
        if download.artwork_url and not enriched.get("artwork_url"):
            enriched["artwork_url"] = download.artwork_url
        if metadata_payload:
            enriched["metadata"] = metadata_payload
        return enriched

    return best_match


def _persist_match(session: Session, match: Match) -> None:
    """Persist a single match, rolling back on failure."""

    _persist_matches(session, [match])


def _persist_matches(session: Session, matches: Iterable[Match]) -> None:
    """Persist multiple matches within a single transaction."""

    try:
        persisted = False
        for match in matches:
            session.add(match)
            persisted = True
        if persisted:
            session.commit()
    except Exception as exc:  # pragma: no cover - database failure is exceptional
        session.rollback()
        logger.error("Failed to persist match result: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to store match result") from exc


@router.post("/spotify-to-soulseek", response_model=MatchingResponse)
def spotify_to_soulseek(
    payload: MatchingRequest,
    engine: MusicMatchingEngine = Depends(get_matching_engine),
    session: Session = Depends(get_db),
) -> MatchingResponse:
    """Match a Spotify track against Soulseek candidates and persist the result."""

    best_candidate: Optional[Dict[str, Any]] = None
    best_score = 0.0
    spotify_track_dto = normalize_spotify_track(payload.spotify_track)
    for candidate in payload.candidates:
        candidate_dto = normalize_slskd_candidate(candidate)
        score = engine.calculate_slskd_match_confidence(spotify_track_dto, candidate_dto)
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
    enriched_match = _attach_download_metadata(best_candidate, session)
    return MatchingResponse(best_match=enriched_match, confidence=best_score)
