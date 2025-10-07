"""In-memory watchlist state service exposed to the public API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock

from app.errors import AppError, ErrorCode, NotFoundError
from app.logging import get_logger
from app.logging_events import log_event


_SENTINEL = object()


@dataclass(slots=True)
class WatchlistEntry:
    """Representation of a watchlist artist stored in memory."""

    id: int
    artist_key: str
    priority: int
    paused: bool
    pause_reason: str | None
    resume_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class WatchlistService:
    """Manage watchlist entries and expose CRUD operations to the API layer."""

    _logger: any = field(default_factory=lambda: get_logger(__name__), init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _entries: dict[str, WatchlistEntry] = field(default_factory=dict, init=False, repr=False)
    _sequence: int = field(default=0, init=False, repr=False)

    def reset(self) -> None:
        """Reset the in-memory state (primarily used in tests)."""

        with self._lock:
            self._entries.clear()
            self._sequence = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_entries(self) -> list[WatchlistEntry]:
        """Return watchlist entries sorted by priority and creation time."""

        with self._lock:
            items = list(self._entries.values())
        return sorted(items, key=lambda entry: (-entry.priority, entry.created_at, entry.id))

    def create_entry(self, *, artist_key: str, priority: int = 0) -> WatchlistEntry:
        key = self._normalise_key(artist_key)
        priority_value = self._validate_priority(priority)

        with self._lock:
            if key in self._entries:
                log_event(
                    self._logger,
                    "service.call",
                    component="service.watchlist",
                    operation="create",
                    status="error",
                    entity_id=key,
                    error="artist_exists",
                )
                raise AppError(
                    "Artist already registered.",
                    code=ErrorCode.VALIDATION_ERROR,
                    http_status=409,
                    meta={"artist_key": key},
                )

            entry = self._build_entry(key, priority_value)
            self._entries[key] = entry

        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="create",
            status="ok",
            entity_id=key,
            priority=priority_value,
        )
        return entry

    def get_entry(self, artist_key: str) -> WatchlistEntry:
        key = self._normalise_key(artist_key)
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            raise NotFoundError("Watchlist entry not found.")
        return entry

    def update_priority(self, *, artist_key: str, priority: int) -> WatchlistEntry:
        key = self._normalise_key(artist_key)
        priority_value = self._validate_priority(priority)

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise NotFoundError("Watchlist entry not found.")
            updated = self._replace(entry, priority=priority_value)
            self._entries[key] = updated

        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="update_priority",
            status="ok",
            entity_id=key,
            priority=priority_value,
        )
        return updated

    def pause_entry(
        self,
        *,
        artist_key: str,
        reason: str | None = None,
        resume_at: datetime | None = None,
    ) -> WatchlistEntry:
        key = self._normalise_key(artist_key)
        pause_reason = self._normalise_reason(reason)

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise NotFoundError("Watchlist entry not found.")
            updated = self._replace(
                entry,
                paused=True,
                pause_reason=pause_reason,
                resume_at=resume_at,
            )
            self._entries[key] = updated

        payload = {
            "component": "service.watchlist",
            "operation": "pause",
            "status": "ok",
            "entity_id": key,
        }
        if pause_reason:
            payload["reason"] = pause_reason
        if resume_at:
            payload["resume_at"] = resume_at.isoformat()
        log_event(self._logger, "service.call", **payload)
        return updated

    def resume_entry(self, *, artist_key: str) -> WatchlistEntry:
        key = self._normalise_key(artist_key)

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise NotFoundError("Watchlist entry not found.")
            updated = self._replace(entry, paused=False, pause_reason=None, resume_at=None)
            self._entries[key] = updated

        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="resume",
            status="ok",
            entity_id=key,
        )
        return updated

    def remove_entry(self, *, artist_key: str) -> None:
        key = self._normalise_key(artist_key)
        with self._lock:
            entry = self._entries.pop(key, None)
        if entry is None:
            raise NotFoundError("Watchlist entry not found.")
        log_event(
            self._logger,
            "service.call",
            component="service.watchlist",
            operation="delete",
            status="ok",
            entity_id=key,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_entry(self, artist_key: str, priority: int) -> WatchlistEntry:
        now = datetime.utcnow()
        self._sequence += 1
        return WatchlistEntry(
            id=self._sequence,
            artist_key=artist_key,
            priority=priority,
            paused=False,
            pause_reason=None,
            resume_at=None,
            created_at=now,
            updated_at=now,
        )

    def _replace(
        self,
        entry: WatchlistEntry,
        *,
        priority: int | None = None,
        paused: bool | None = None,
        pause_reason: str | None | object = _SENTINEL,
        resume_at: datetime | None | object = _SENTINEL,
    ) -> WatchlistEntry:
        new_priority = entry.priority if priority is None else priority
        new_paused = entry.paused if paused is None else paused
        new_reason = entry.pause_reason if pause_reason is _SENTINEL else pause_reason
        new_resume = entry.resume_at if resume_at is _SENTINEL else resume_at

        if not new_paused:
            new_reason = None
            new_resume = None

        return WatchlistEntry(
            id=entry.id,
            artist_key=entry.artist_key,
            priority=new_priority,
            paused=new_paused,
            pause_reason=new_reason,
            resume_at=new_resume,
            created_at=entry.created_at,
            updated_at=datetime.utcnow(),
        )

    @staticmethod
    def _normalise_key(value: str) -> str:
        candidate = (value or "").strip()
        if not candidate:
            raise AppError(
                "artist_key must not be empty.",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            )
        return candidate

    @staticmethod
    def _validate_priority(value: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise AppError(
                "priority must be an integer.",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            ) from exc

    @staticmethod
    def _normalise_reason(reason: str | None) -> str | None:
        if reason is None:
            return None
        candidate = reason.strip()
        return candidate or None


__all__ = ["WatchlistEntry", "WatchlistService"]

