"""Watchlist management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.dependencies import get_watchlist_service
from app.schemas import WatchlistArtistCreate, WatchlistArtistEntry, WatchlistListResponse
from app.services.watchlist_service import WatchlistService


router = APIRouter(prefix="/watchlist", tags=["Watchlist"])


@router.get("", response_model=WatchlistListResponse)
def list_watchlist(
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistListResponse:
    """Return all registered watchlist artists."""

    return service.list_artists()


@router.post(
    "",
    response_model=WatchlistArtistEntry,
    status_code=status.HTTP_201_CREATED,
)
def add_watchlist_artist(
    payload: WatchlistArtistCreate,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistArtistEntry:
    """Add a new artist to the automated release watchlist."""

    return service.add_artist(payload)


@router.delete("/{artist_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist_artist(
    artist_id: int,
    service: WatchlistService = Depends(get_watchlist_service),
) -> Response:
    """Remove an artist from the release watchlist."""

    service.remove_artist(int(artist_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
