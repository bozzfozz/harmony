"""Watchlist management endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.logging import get_logger
from app.models import WatchlistArtist
from app.schemas import (
    WatchlistArtistCreate,
    WatchlistArtistEntry,
    WatchlistListResponse,
)

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])
logger = get_logger(__name__)


@router.get("", response_model=WatchlistListResponse)
def list_watchlist(session: Session = Depends(get_db)) -> WatchlistListResponse:
    """Return all registered watchlist artists."""

    records = (
        session.execute(select(WatchlistArtist).order_by(WatchlistArtist.created_at.asc()))
        .scalars()
        .all()
    )
    logger.debug("Fetched %d watchlist artist(s)", len(records))
    items = [WatchlistArtistEntry.model_validate(record) for record in records]
    return WatchlistListResponse(items=items)


@router.post(
    "",
    response_model=WatchlistArtistEntry,
    status_code=status.HTTP_201_CREATED,
)
def add_watchlist_artist(
    payload: WatchlistArtistCreate,
    session: Session = Depends(get_db),
) -> WatchlistArtistEntry:
    """Add a new artist to the automated release watchlist."""

    spotify_id = payload.spotify_artist_id.strip()
    name = payload.name.strip()

    existing = (
        session.execute(
            select(WatchlistArtist).where(WatchlistArtist.spotify_artist_id == spotify_id)
        )
        .scalars()
        .first()
    )
    if existing is not None:
        logger.info("Watchlist artist %s already registered", spotify_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Artist already registered",
        )

    now = datetime.utcnow()
    record = WatchlistArtist(
        spotify_artist_id=spotify_id,
        name=name,
        last_checked=now,
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    logger.info("Added %s (%s) to watchlist", name, spotify_id)
    return WatchlistArtistEntry.model_validate(record)


@router.delete("/{artist_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist_artist(
    artist_id: int,
    session: Session = Depends(get_db),
) -> Response:
    """Remove an artist from the release watchlist."""

    record = session.get(WatchlistArtist, int(artist_id))
    if record is None:
        logger.info("Watchlist artist %s not found for deletion", artist_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist artist not found",
        )

    session.delete(record)
    session.commit()
    logger.info("Removed %s (%s) from watchlist", record.name, record.spotify_artist_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
