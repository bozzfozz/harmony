from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.soulseek_client import SoulseekClient, TrackResult
from app.db import get_db
from app.models import Song
from app.utils.logging_config import get_logger


logger = get_logger("soulseek_router")
router = APIRouter()


class SoulseekSearchResult(BaseModel):
    username: str
    filename: str
    size: int
    bitrate: int | None = None
    duration: int | None = None
    quality: str | None = None
    confidence: float | None = None


class SoulseekDownloadRequest(BaseModel):
    username: str
    filename: str
    size: int
    bitrate: int | None = None
    duration: int | None = None
    quality: str | None = None


class SoulseekSongOut(BaseModel):
    id: int
    title: str
    artist: str
    album: str
    duration: int | None
    source: str

    class Config:
        orm_mode = True


_client = SoulseekClient()


def _extract_tracks(results: List[TrackResult] | tuple[List[TrackResult], object]) -> List[TrackResult]:
    if isinstance(results, tuple):
        return results[0]
    return results


@router.get("/search", response_model=List[SoulseekSearchResult])
async def search_tracks(query: str = Query(..., description="Suchbegriff für Soulseek")) -> List[SoulseekSearchResult]:
    """Search for tracks on Soulseek via slskd."""

    try:
        results = await _client.search(query)
        tracks = _extract_tracks(results)
        return [
            SoulseekSearchResult(
                username=track.username,
                filename=track.filename,
                size=track.size,
                bitrate=getattr(track, "bitrate", getattr(track, "bit_rate", None)),
                duration=getattr(track, "duration", None),
                quality=getattr(track, "quality", None),
                confidence=getattr(track, "confidence", None),
            )
            for track in tracks
        ]
    except Exception as exc:  # pragma: no cover - defensive safeguard
        logger.error("Soulseek search failed: %s", exc)
        raise HTTPException(status_code=500, detail="Soulseek-Suche fehlgeschlagen") from exc


@router.post("/download", response_model=SoulseekSongOut)
async def download_track(
    request: SoulseekDownloadRequest, db: Session = Depends(get_db)
) -> SoulseekSongOut:
    """Download a Soulseek track and persist it in the database."""

    try:
        started = await _client.download(
            username=request.username,
            filename=request.filename,
            size=request.size,
        )
        if not started:
            raise HTTPException(status_code=502, detail="Download konnte nicht gestartet werden")

        song = Song(
            title=request.filename,
            artist="Unknown",
            album="Unknown",
            duration=request.duration,
            source="soulseek",
            path=request.filename,
        )
        db.add(song)
        db.commit()
        db.refresh(song)

        logger.info("Song '%s' von %s gespeichert", song.title, request.username)
        return SoulseekSongOut.from_orm(song)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive safeguard
        logger.error("Soulseek download failed: %s", exc)
        db.rollback()
        raise HTTPException(status_code=500, detail="Soulseek-Download fehlgeschlagen") from exc


@router.get("/songs", response_model=List[SoulseekSongOut])
def list_downloaded_songs(db: Session = Depends(get_db)) -> List[SoulseekSongOut]:
    """List all Soulseek downloads stored in the database."""

    songs = db.query(Song).filter(Song.source == "soulseek").all()
    return [SoulseekSongOut.from_orm(song) for song in songs]
