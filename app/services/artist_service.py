"""Service facade exposing artist and watchlist operations for the public API."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any, Awaitable, Callable, Sequence

from app.errors import DependencyError, InternalServerError, NotFoundError, ValidationAppError
from app.logging import get_logger
from app.logging_events import log_event
from app.services.artist_dao import (
    ArtistDao,
    ArtistReleaseRow,
    ArtistRow,
    ArtistWatchlistEntryRow,
)
from app.workers import persistence
from app.workers.persistence import QueueJobDTO
from app.utils.idempotency import make_idempotency_key


_ARTIST_SYNC_JOB = "artist_sync"


@dataclass(slots=True)
class ArtistDetails:
    artist: ArtistRow
    releases: Sequence[ArtistReleaseRow]


@dataclass(slots=True)
class WatchlistPage:
    items: list[ArtistWatchlistEntryRow]
    total: int
    limit: int
    offset: int


@dataclass(slots=True)
class EnqueueResult:
    job: QueueJobDTO
    already_enqueued: bool


@dataclass(slots=True)
class ArtistService:
    """Expose artist centric operations for the API layer."""

    dao: ArtistDao = field(default_factory=ArtistDao)
    _enqueue_fn: Callable[..., Awaitable[QueueJobDTO]] | None = field(default=None, repr=False)
    _persistence_module: Any = field(default=persistence, repr=False)
    _logger: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:  # pragma: no cover - attribute wiring
        object.__setattr__(self, "_logger", get_logger(__name__))

    def _normalise_key(self, artist_key: str) -> str:
        return (artist_key or "").strip()

    def get_artist(self, artist_key: str) -> ArtistDetails:
        """Return an artist along with their known releases."""

        key = self._normalise_key(artist_key)
        if not key:
            raise ValidationAppError("artist_key must not be empty.")

        start = perf_counter()
        try:
            artist = self.dao.get_artist(key)
            if artist is None:
                duration_ms = (perf_counter() - start) * 1000
                log_event(
                    self._logger,
                    "service.call",
                    component="service.artist",
                    operation="get_artist",
                    status="not_found",
                    duration_ms=round(duration_ms, 3),
                    entity_id=key,
                )
                raise NotFoundError("Artist not found.")
            releases = self.dao.get_artist_releases(key)
        except NotFoundError:
            raise
        except Exception as exc:  # pragma: no cover - defensive logging path
            duration_ms = (perf_counter() - start) * 1000
            log_event(
                self._logger,
                "service.call",
                component="service.artist",
                operation="get_artist",
                status="error",
                duration_ms=round(duration_ms, 3),
                entity_id=key,
                error="dao_failure",
            )
            raise InternalServerError("Failed to load artist data.") from exc

        duration_ms = (perf_counter() - start) * 1000
        log_event(
            self._logger,
            "service.call",
            component="service.artist",
            operation="get_artist",
            status="ok",
            duration_ms=round(duration_ms, 3),
            entity_id=key,
            result_count=len(releases),
        )
        return ArtistDetails(artist=artist, releases=releases)

    def list_watchlist(self, *, limit: int = 50, offset: int = 0) -> WatchlistPage:
        """Return a paginated view of the artist watchlist."""

        if limit <= 0:
            raise ValidationAppError("limit must be greater than zero.")
        if offset < 0:
            raise ValidationAppError("offset must be zero or positive.")

        capped_limit = min(limit, 100)
        start = perf_counter()
        try:
            items, total = self.dao.list_watchlist_entries(limit=capped_limit, offset=offset)
        except Exception as exc:  # pragma: no cover - defensive logging path
            duration_ms = (perf_counter() - start) * 1000
            log_event(
                self._logger,
                "service.call",
                component="service.artist",
                operation="list_watchlist",
                status="error",
                duration_ms=round(duration_ms, 3),
                meta={"limit": capped_limit, "offset": offset},
                error="dao_failure",
            )
            raise InternalServerError("Failed to load watchlist entries.") from exc

        duration_ms = (perf_counter() - start) * 1000
        log_event(
            self._logger,
            "service.call",
            component="service.artist",
            operation="list_watchlist",
            status="ok",
            duration_ms=round(duration_ms, 3),
            result_count=len(items),
            meta={"limit": capped_limit, "offset": offset, "total": total},
        )
        return WatchlistPage(items=list(items), total=total, limit=capped_limit, offset=offset)

    def upsert_watchlist(
        self,
        *,
        artist_key: str,
        priority: int | None = None,
        cooldown_until: datetime | None = None,
    ) -> ArtistWatchlistEntryRow:
        """Add or update an artist watchlist entry."""

        key = self._normalise_key(artist_key)
        if not key:
            raise ValidationAppError("artist_key must not be empty.")
        try:
            resolved_priority = int(priority) if priority is not None else 0
        except (TypeError, ValueError):
            raise ValidationAppError("priority must be an integer.")

        start = perf_counter()
        try:
            entry = self.dao.upsert_watchlist_entry(
                key,
                priority=resolved_priority,
                cooldown_until=cooldown_until,
            )
        except ValueError as exc:
            raise ValidationAppError(str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive logging path
            duration_ms = (perf_counter() - start) * 1000
            log_event(
                self._logger,
                "service.call",
                component="service.artist",
                operation="upsert_watchlist",
                status="error",
                duration_ms=round(duration_ms, 3),
                entity_id=key,
                error="dao_failure",
            )
            raise InternalServerError("Failed to update watchlist entry.") from exc

        duration_ms = (perf_counter() - start) * 1000
        log_event(
            self._logger,
            "service.call",
            component="service.artist",
            operation="upsert_watchlist",
            status="ok",
            duration_ms=round(duration_ms, 3),
            entity_id=key,
            meta={"priority": resolved_priority},
        )
        return entry

    def remove_watchlist(self, artist_key: str) -> None:
        """Remove an artist from the watchlist."""

        key = self._normalise_key(artist_key)
        if not key:
            raise ValidationAppError("artist_key must not be empty.")

        start = perf_counter()
        try:
            removed = self.dao.remove_watchlist_entry(key)
        except Exception as exc:  # pragma: no cover - defensive logging path
            duration_ms = (perf_counter() - start) * 1000
            log_event(
                self._logger,
                "service.call",
                component="service.artist",
                operation="remove_watchlist",
                status="error",
                duration_ms=round(duration_ms, 3),
                entity_id=key,
                error="dao_failure",
            )
            raise InternalServerError("Failed to remove watchlist entry.") from exc

        if not removed:
            duration_ms = (perf_counter() - start) * 1000
            log_event(
                self._logger,
                "service.call",
                component="service.artist",
                operation="remove_watchlist",
                status="not_found",
                duration_ms=round(duration_ms, 3),
                entity_id=key,
            )
            raise NotFoundError("Watchlist entry not found.")

        duration_ms = (perf_counter() - start) * 1000
        log_event(
            self._logger,
            "service.call",
            component="service.artist",
            operation="remove_watchlist",
            status="ok",
            duration_ms=round(duration_ms, 3),
            entity_id=key,
        )

    async def enqueue_sync(self, artist_key: str) -> EnqueueResult:
        """Schedule an artist sync job in the orchestrator queue."""

        key = self._normalise_key(artist_key)
        if not key:
            raise ValidationAppError("artist_key must not be empty.")

        payload = {"artist_key": key}
        idempotency_hint = json.dumps(payload, sort_keys=True, default=str)
        idempotency_key = make_idempotency_key(_ARTIST_SYNC_JOB, key, idempotency_hint)
        existing = self._persistence_module.find_by_idempotency(_ARTIST_SYNC_JOB, idempotency_key)

        start = perf_counter()
        try:
            enqueue = self._resolve_enqueue_fn()
            job = await enqueue(key, idempotency_hint=idempotency_hint)
        except ValidationAppError:
            raise
        except ValueError as exc:
            raise ValidationAppError(str(exc)) from exc
        except DependencyError:
            raise
        except Exception as exc:
            duration_ms = (perf_counter() - start) * 1000
            log_event(
                self._logger,
                "service.call",
                component="service.artist",
                operation="enqueue_sync",
                status="error",
                duration_ms=round(duration_ms, 3),
                entity_id=key,
                error="enqueue_failed",
            )
            raise DependencyError("Failed to enqueue artist sync.") from exc

        duration_ms = (perf_counter() - start) * 1000
        already_enqueued = existing is not None
        log_event(
            self._logger,
            "service.call",
            component="service.artist",
            operation="enqueue_sync",
            status="ok",
            duration_ms=round(duration_ms, 3),
            entity_id=key,
            meta={"already_enqueued": already_enqueued, "job_id": int(job.id)},
        )
        return EnqueueResult(job=job, already_enqueued=already_enqueued)

    def _resolve_enqueue_fn(self) -> Callable[..., Awaitable[QueueJobDTO]]:
        fn = self._enqueue_fn
        if fn is not None:
            return fn
        from app.orchestrator.artist_sync import (
            enqueue_artist_sync as _enqueue,
        )  # local import to avoid circulars

        object.__setattr__(self, "_enqueue_fn", _enqueue)
        return _enqueue


__all__ = [
    "ArtistDetails",
    "ArtistService",
    "EnqueueResult",
    "WatchlistPage",
]
