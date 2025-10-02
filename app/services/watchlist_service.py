"""Service layer for managing watchlist artists via the public API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from logging import Logger

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError, ErrorCode, NotFoundError
from app.logging import get_logger
from app.logging_events import log_event
from app.models import WatchlistArtist
from app.schemas import (
    WatchlistArtistCreate,
    WatchlistArtistEntry,
    WatchlistListResponse,
)


@dataclass(slots=True)
class WatchlistService:
    """Expose CRUD operations for watchlist artists."""

    session: Session
    _logger: Logger = field(init=False, repr=False)

    def __post_init__(self) -> None:  # pragma: no cover - simple assignment
        object.__setattr__(self, "_logger", get_logger(__name__))

    def list_artists(self) -> WatchlistListResponse:
        """Return all artists ordered by creation timestamp."""

        start = perf_counter()
        statement = select(WatchlistArtist).order_by(WatchlistArtist.created_at.asc())
        artists = self.session.execute(statement).scalars().all()
        duration_ms = (perf_counter() - start) * 1_000
        items = [WatchlistArtistEntry.model_validate(record) for record in artists]
        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="list",
            status="ok",
            duration_ms=round(duration_ms, 3),
            result_count=len(items),
        )
        return WatchlistListResponse(items=items)

    def add_artist(self, payload: WatchlistArtistCreate) -> WatchlistArtistEntry:
        """Persist a new watchlist artist if it does not already exist."""

        spotify_id = payload.spotify_artist_id.strip()
        name = payload.name.strip()
        start = perf_counter()

        existing = (
            self.session.execute(
                select(WatchlistArtist).where(WatchlistArtist.spotify_artist_id == spotify_id)
            )
            .scalars()
            .first()
        )
        if existing is not None:
            duration_ms = (perf_counter() - start) * 1_000
            log_event(
                self._logger,
                "service.call",
                component="service.watchlist",
                operation="add",
                status="error",
                duration_ms=round(duration_ms, 3),
                entity_id=str(existing.id),
                spotify_artist_id=spotify_id,
                error="artist_exists",
            )
            raise AppError(
                "Artist already registered.",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=409,
                meta={"spotify_artist_id": spotify_id},
            )

        now = datetime.utcnow()
        record = WatchlistArtist(
            spotify_artist_id=spotify_id,
            name=name,
            last_checked=now,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)

        duration_ms = (perf_counter() - start) * 1_000
        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="add",
            status="ok",
            duration_ms=round(duration_ms, 3),
            entity_id=str(record.id),
            spotify_artist_id=spotify_id,
        )
        return WatchlistArtistEntry.model_validate(record)

    def remove_artist(self, artist_id: int) -> None:
        """Remove an artist from the watchlist or raise if missing."""

        start = perf_counter()
        record = self.session.get(WatchlistArtist, int(artist_id))
        if record is None:
            duration_ms = (perf_counter() - start) * 1_000
            log_event(
                self._logger,
                "service.call",
                component="service.watchlist",
                operation="remove",
                status="error",
                duration_ms=round(duration_ms, 3),
                entity_id=str(artist_id),
                error="not_found",
            )
            raise NotFoundError("Watchlist artist not found.")

        self.session.delete(record)
        self.session.commit()

        duration_ms = (perf_counter() - start) * 1_000
        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="remove",
            status="ok",
            duration_ms=round(duration_ms, 3),
            entity_id=str(artist_id),
            spotify_artist_id=record.spotify_artist_id,
        )


__all__ = ["WatchlistService"]
