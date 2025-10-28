"""Activity feed management for recent Harmony backend events."""

from __future__ import annotations

import asyncio
import builtins
from collections import OrderedDict, deque
from collections.abc import Iterable, MutableMapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
import json
from threading import Lock
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
)

from sqlalchemy import func

from app.db import session_scope
from app.logging import get_logger
from app.models import ActivityEvent
from app.utils.events import (
    WORKER_RESTARTED,
    WORKER_STALE,
    WORKER_STARTED,
    WORKER_STOPPED,
)
from app.utils.worker_health import read_worker_status

if TYPE_CHECKING:
    from app.services.cache import ResponseCache

logger = get_logger(__name__)


def _timestamp_to_utc_isoformat(value: datetime) -> str:
    """Return a UTC-normalised ISO 8601 representation ending with Z."""

    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        normalised = value.replace(tzinfo=UTC)
    else:
        normalised = value.astimezone(UTC)
    iso_value = normalised.isoformat()
    if iso_value.endswith("+00:00"):
        return f"{iso_value[:-6]}Z"
    return iso_value


@dataclass(frozen=True)
class ActivityEntry:
    """Immutable record representing a single activity entry."""

    timestamp: datetime
    type: str
    status: str
    details: MutableMapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """Return a serialisable representation of the entry."""

        payload: dict[str, object] = {
            "timestamp": _timestamp_to_utc_isoformat(self.timestamp),
            "type": self.type,
            "status": self.status,
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


_PageCacheEntry = tuple[tuple["ActivityEntry", ...], int]


class ActivityManager:
    """Manage a bounded list of recent activity events."""

    def __init__(self, max_entries: int = 50, page_cache_limit: int = 128) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._entries: deque[ActivityEntry] = deque(maxlen=max_entries)
        self._lock = Lock()
        self._cache_initialized = False
        self._page_cache: OrderedDict[tuple[int, int, str | None, str | None], _PageCacheEntry] = (
            OrderedDict()
        )
        self._page_cache_limit = max(1, page_cache_limit)
        self._response_cache: ResponseCache | None = None
        self._response_cache_paths: tuple[str, ...] = ()

    def _entry_from_event(self, event: ActivityEvent) -> ActivityEntry:
        details: MutableMapping[str, object] = dict(event.details or {})
        return ActivityEntry(
            timestamp=event.timestamp,
            type=event.type,
            status=event.status,
            details=details,
        )

    def refresh_cache(self) -> None:
        """Reload the in-memory cache from the database."""

        with session_scope() as session:
            events = (
                session.query(ActivityEvent)
                .order_by(ActivityEvent.timestamp.desc(), ActivityEvent.id.desc())
                .limit(self._max_entries)
                .all()
            )

        entries = deque(
            (self._entry_from_event(event) for event in events),
            maxlen=self._max_entries,
        )

        with self._lock:
            self._entries.clear()
            self._entries.extend(entries)
            self._cache_initialized = True
            self._page_cache.clear()
        self._invalidate_response_cache()

    def _ensure_cache(self) -> None:
        if not self._cache_initialized:
            self.refresh_cache()

    def _cache_key(
        self,
        *,
        limit: int,
        offset: int,
        type_filter: str | None,
        status_filter: str | None,
    ) -> tuple[int, int, str | None, str | None]:
        return (limit, offset, type_filter, status_filter)

    def record(
        self,
        *,
        action_type: str,
        status: str,
        timestamp: datetime | None = None,
        details: MutableMapping[str, object] | None = None,
    ) -> ActivityEntry:
        """Append a new entry to the feed, persist it and return it."""

        details_payload: MutableMapping[str, object] = _serialise_details(details)
        event = ActivityEvent(
            type=action_type,
            status=status,
            details=details_payload or None,
        )
        if timestamp is not None:
            event.timestamp = timestamp

        with session_scope() as session:
            session.add(event)

        entry = self._entry_from_event(event)

        with self._lock:
            self._entries.appendleft(entry)
            self._cache_initialized = True
            self._page_cache.clear()

        self._invalidate_response_cache()
        return entry

    def list(self) -> builtins.list[dict[str, object]]:
        """Return a copy of the cached entries in newest-first order."""

        self._ensure_cache()
        with self._lock:
            return [entry.as_dict() for entry in self._entries]

    def fetch(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        type_filter: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[builtins.list[dict[str, object]], int]:
        """Return entries directly from the database with paging/filter support."""

        filters = []
        if type_filter:
            filters.append(ActivityEvent.type == type_filter)
        if status_filter:
            filters.append(ActivityEvent.status == status_filter)

        cache_key = self._cache_key(
            limit=limit,
            offset=offset,
            type_filter=type_filter,
            status_filter=status_filter,
        )

        with self._lock:
            cached = self._page_cache.get(cache_key)
            if cached is not None:
                self._page_cache.move_to_end(cache_key)
                cached_entries, cached_total = cached
                return [entry.as_dict() for entry in cached_entries], cached_total

        with session_scope() as session:
            count_query = session.query(func.count(ActivityEvent.id))
            events_query = session.query(ActivityEvent)
            if filters:
                count_query = count_query.filter(*filters)
                events_query = events_query.filter(*filters)

            total = (count_query.scalar()) or 0

            events = (
                events_query.order_by(ActivityEvent.timestamp.desc(), ActivityEvent.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

        total_int = int(total)
        entries = tuple(self._entry_from_event(event) for event in events)

        with self._lock:
            self._page_cache[cache_key] = (entries, total_int)
            self._page_cache.move_to_end(cache_key)
            while len(self._page_cache) > self._page_cache_limit:
                self._page_cache.popitem(last=False)

        return [entry.as_dict() for entry in entries], total_int

    def extend(self, entries: Iterable[ActivityEntry]) -> None:
        """Insert multiple entries into the cache, preserving their order."""

        with self._lock:
            for entry in reversed(list(entries)):
                self._entries.appendleft(entry)
            self._cache_initialized = True
            self._page_cache.clear()
        self._invalidate_response_cache()

    def clear(self) -> None:
        """Remove all cached entries without touching persistent storage."""

        with self._lock:
            self._entries.clear()
            self._cache_initialized = False
            self._page_cache.clear()
        self._invalidate_response_cache()

    def configure_response_cache(
        self,
        cache: ResponseCache | None,
        *,
        paths: Iterable[str] | None = None,
    ) -> None:
        """Configure the HTTP response cache invalidation strategy."""

        normalized_paths = self._normalise_cache_paths(paths or ())
        with self._lock:
            self._response_cache = cache
            self._response_cache_paths = normalized_paths

    def _invalidate_response_cache(self) -> None:
        cache = self._response_cache
        paths = self._response_cache_paths
        if cache is None or not paths:
            return

        async def _invalidate_async() -> None:
            for path in paths:
                try:
                    await cache.invalidate_path(path, reason="activity_updated")
                except Exception:  # pragma: no cover - defensive logging
                    logger.exception(
                        "Failed to invalidate response cache for activity path",
                        extra={"path": path},
                    )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_invalidate_async())
            return

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_invalidate_async()))

    @staticmethod
    def _normalise_cache_paths(paths: Iterable[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in paths:
            if not raw:
                continue
            path = raw if raw.startswith("/") else f"/{raw}"
            if len(path) > 1 and path.endswith("/"):
                path = path.rstrip("/")
            if path not in seen:
                ordered.append(path)
                seen.add(path)
        return tuple(ordered)

    def serialise_event(self, event: ActivityEvent) -> dict[str, object]:
        """Return the API representation for a stored activity event."""

        return self._entry_from_event(event).as_dict()


def _serialise_details(
    details: MutableMapping[str, object] | None | None,
) -> MutableMapping[str, object]:
    """Normalise detail payloads so they can be stored as JSON."""

    def _convert(value: Any) -> Any:
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, dict):
            return {str(key): _convert(val) for key, val in value.items()}
        if isinstance(value, list | tuple):
            return [_convert(item) for item in value]
        if isinstance(value, set):
            converted = [_convert(item) for item in value]
            try:
                return sorted(converted)
            except TypeError:
                return sorted(converted, key=_set_sort_key)
        if isinstance(value, datetime):
            return _timestamp_to_utc_isoformat(value)
        if is_dataclass(value) and not isinstance(value, type):
            return _convert(asdict(value))
        converter = getattr(value, "as_dict", None)
        if callable(converter):
            return _convert(converter())
        return str(value)

    if not details:
        return {}
    return {str(key): _convert(val) for key, val in details.items()}


def _set_sort_key(value: Any) -> tuple[str, object]:
    """Return a deterministic sort key for set members.

    Falls back to JSON serialisation when natural ordering is unavailable to
    ensure a stable ordering for complex structures such as dicts.
    """

    type_name = type(value).__qualname__
    if isinstance(value, int | float | str):
        return type_name, value
    try:
        serialised = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except TypeError:
        serialised = repr(value)
    return type_name, serialised


activity_manager = ActivityManager()


def record_activity(
    action_type: str,
    status: str,
    *,
    timestamp: datetime | None = None,
    details: MutableMapping[str, object] | None = None,
) -> dict[str, object]:
    """Record an activity and return its serialised representation."""

    entry = activity_manager.record(
        action_type=action_type,
        status=status,
        timestamp=timestamp,
        details=details,
    )
    return entry.as_dict()


WorkerActivityStatus = Literal[
    "started",
    "stopped",
    "stale",
    "restarted",
]


def _normalise_timestamp(value: datetime) -> datetime:
    """Ensure timestamps stored in worker events are naive UTC values."""

    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def record_worker_event(
    worker: str,
    status: WorkerActivityStatus,
    *,
    timestamp: datetime | None = None,
    details: MutableMapping[str, object] | None = None,
) -> dict[str, object]:
    """Persist a worker lifecycle/health event in the activity feed."""

    event_time = _normalise_timestamp(timestamp or datetime.utcnow())
    payload: dict[str, object] = {"worker": worker}
    if details:
        payload.update(dict(details))
    payload.setdefault("timestamp", event_time)
    return record_activity("worker", status, timestamp=event_time, details=payload)


def record_worker_started(
    worker: str,
    *,
    timestamp: datetime | None = None,
) -> dict[str, object]:
    """Record a worker start or restart event depending on prior status."""

    _, stored_status = read_worker_status(worker)
    previous = (stored_status or "").lower()
    status: WorkerActivityStatus = (
        WORKER_RESTARTED if previous in {WORKER_STOPPED, WORKER_STALE} else WORKER_STARTED
    )
    extra: dict[str, object] = {}
    if status == WORKER_RESTARTED and previous:
        extra["previous_status"] = previous
    return record_worker_event(worker, status, timestamp=timestamp, details=extra)


def record_worker_restarted(
    worker: str,
    *,
    timestamp: datetime | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """Explicitly record a worker restart event with optional reason."""

    extra: dict[str, object] = {}
    if reason:
        extra["reason"] = reason
    return record_worker_event(worker, WORKER_RESTARTED, timestamp=timestamp, details=extra)


def record_worker_stopped(
    worker: str,
    *,
    timestamp: datetime | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """Record a worker shutdown event in the activity feed."""

    extra: dict[str, object] = {}
    if reason:
        extra["reason"] = reason
    return record_worker_event(worker, WORKER_STOPPED, timestamp=timestamp, details=extra)


def record_worker_stale(
    worker: str,
    *,
    last_seen: str | None,
    threshold_seconds: float,
    elapsed_seconds: float | None = None,
    timestamp: datetime | None = None,
) -> dict[str, object]:
    """Record that a worker missed its heartbeat threshold."""

    extra: dict[str, object] = {"threshold_seconds": float(threshold_seconds)}
    if last_seen:
        extra["last_seen"] = last_seen
    if elapsed_seconds is not None:
        extra["elapsed_seconds"] = round(float(elapsed_seconds), 2)
    return record_worker_event(worker, WORKER_STALE, timestamp=timestamp, details=extra)
