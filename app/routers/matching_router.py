"""Matching endpoints for Harmony."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.matching_engine import MusicMatchingEngine
from app.dependencies import get_db, get_matching_engine
from app.logging import get_logger
from app.models import Download, Match
from app.schemas import (
    AlbumMatchingRequest,
    DiscographyMatchingRequest,
    DiscographyMatchingResponse,
    DiscographyMissingAlbum,
    DiscographyMissingTrack,
    MatchingRequest,
    MatchingResponse,
)

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


def _extract_album_tracks(album: Dict[str, Any]) -> List[Dict[str, Any]]:
    tracks = album.get("tracks")
    if isinstance(tracks, dict):
        items = tracks.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(tracks, list):
        return [item for item in tracks if isinstance(item, dict)]
    return []


def _extract_spotify_track_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if value.startswith("spotify://track:"):
        return value.split(":")[-1]
    if value.startswith("spotify:track:"):
        return value.split(":")[-1]
    if "spotify.com/track/" in value:
        return value.rsplit("/", 1)[-1]
    return None


def _extract_track_identifier(candidate: Dict[str, Any]) -> Optional[str]:
    guid = candidate.get("guid")
    track_id = _extract_spotify_track_id(guid if isinstance(guid, str) else None)
    if track_id:
        return track_id

    guids = candidate.get("Guid")
    if isinstance(guids, list):
        for entry in guids:
            if not isinstance(entry, dict):
                continue
            parsed = _extract_spotify_track_id(entry.get("id"))
            if parsed:
                return parsed

    for key in ("ratingKey", "id", "key"):
        value = candidate.get(key)
        if isinstance(value, str) and value.startswith("spotify:"):
            parsed = _extract_spotify_track_id(value)
            if parsed:
                return parsed
    return None


def calculate_discography_missing(
    artist_id: str,
    albums: List[Dict[str, Any]],
    plex_items: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Determine which Spotify tracks are missing from Plex for a discography."""

    existing_ids: set[str] = set()
    for item in plex_items:
        if not isinstance(item, dict):
            continue
        track_id = _extract_track_identifier(item)
        if track_id:
            existing_ids.add(track_id)

    missing_albums: List[Dict[str, Any]] = []
    missing_tracks: List[Dict[str, Any]] = []

    for album_entry in albums:
        if not isinstance(album_entry, dict):
            continue
        album_data = (
            album_entry.get("album") if isinstance(album_entry.get("album"), dict) else album_entry
        )
        track_entries = album_entry.get("tracks")
        if isinstance(track_entries, list):
            tracks = [track for track in track_entries if isinstance(track, dict)]
        else:
            tracks = _extract_album_tracks(album_entry)
        album_missing: List[Dict[str, Any]] = []
        for track in tracks:
            track_id = track.get("id") or track.get("spotify_id")
            if not track_id:
                continue
            if track_id in existing_ids:
                continue
            album_missing.append(track)
            missing_tracks.append({"album": album_data, "track": track})
        if album_missing:
            missing_albums.append({"album": album_data, "missing_tracks": album_missing})

    return missing_albums, missing_tracks


@router.post("/spotify-to-plex", response_model=MatchingResponse)
def spotify_to_plex(
    payload: MatchingRequest,
    engine: MusicMatchingEngine = Depends(get_matching_engine),
    session: Session = Depends(get_db),
) -> MatchingResponse:
    """Match a Spotify track against Plex candidates and persist the result."""

    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Plex matching is disabled while the integration is archived",
    )

    best_match, confidence = engine.find_best_match(payload.spotify_track, payload.candidates)
    target_id = _extract_target_id(best_match)
    match = Match(
        source="spotify-to-plex",
        spotify_track_id=str(payload.spotify_track.get("id")),
        target_id=target_id,
        confidence=confidence,
    )
    _persist_match(session, match)
    enriched_match = _attach_download_metadata(best_match, session)
    return MatchingResponse(best_match=enriched_match, confidence=confidence)


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
    enriched_match = _attach_download_metadata(best_candidate, session)
    return MatchingResponse(best_match=enriched_match, confidence=best_score)


@router.post("/spotify-to-plex-album", response_model=MatchingResponse)
def spotify_to_plex_album(
    payload: AlbumMatchingRequest,
    engine: MusicMatchingEngine = Depends(get_matching_engine),
    persist: bool = Query(False, description="Persist album matches for individual tracks"),
    session: Session = Depends(get_db),
) -> MatchingResponse:
    """Return the best matching Plex album for the provided Spotify album."""

    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Plex matching is disabled while the integration is archived",
    )

    best_match, confidence = engine.find_best_album_match(payload.spotify_album, payload.candidates)
    if persist:
        album_id = payload.spotify_album.get("id")
        target_id = _extract_target_id(best_match)
        matches = []
        for track in _extract_album_tracks(payload.spotify_album):
            track_id = track.get("id")
            if track_id is None:
                continue
            matches.append(
                Match(
                    source="spotify-to-plex-album",
                    spotify_track_id=str(track_id),
                    target_id=target_id,
                    context_id=str(album_id) if album_id is not None else None,
                    confidence=confidence,
                )
            )
        if matches:
            _persist_matches(session, matches)
    return MatchingResponse(best_match=best_match, confidence=confidence)


@router.post("/discography/plex", response_model=DiscographyMatchingResponse)
def discography_to_plex(
    payload: DiscographyMatchingRequest,
) -> DiscographyMatchingResponse:
    """Return missing Spotify tracks for a complete discography."""

    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Plex matching is disabled while the integration is archived",
    )

    missing_albums, missing_tracks = calculate_discography_missing(
        payload.artist_id,
        payload.albums,
        payload.plex_items,
    )
    return DiscographyMatchingResponse(
        missing_albums=[
            DiscographyMissingAlbum(
                album=item.get("album", {}), missing_tracks=item.get("missing_tracks", [])
            )
            for item in missing_albums
        ],
        missing_tracks=[
            DiscographyMissingTrack(album=item.get("album", {}), track=item.get("track", {}))
            for item in missing_tracks
        ],
    )
