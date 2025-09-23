"""Activity feed management for recent Harmony backend events."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Deque, Dict, Iterable, List, Literal, MutableMapping, Optional

ActivityType = Literal["sync", "search", "download", "metadata"]


@dataclass(frozen=True)
class ActivityEntry:
    """Immutable record representing a single activity entry."""

    timestamp: datetime
    type: ActivityType
    status: str
    details: MutableMapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        """Return a serialisable representation of the entry."""

        payload: Dict[str, object] = {
            "timestamp": self.timestamp.isoformat() + "Z",
            "type": self.type,
            "status": self.status,
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


class ActivityManager:
    """Manage a bounded list of recent activity events."""

    def __init__(self, max_entries: int = 50) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._entries: Deque[ActivityEntry] = deque(maxlen=max_entries)
        self._lock = Lock()

    def record(
        self,
        *,
        action_type: ActivityType,
        status: str,
        timestamp: Optional[datetime] = None,
        details: Optional[MutableMapping[str, object]] = None,
    ) -> ActivityEntry:
        """Append a new entry to the feed and return it."""

        details_payload: MutableMapping[str, object] = dict(details or {})
        entry = ActivityEntry(
            timestamp=timestamp or datetime.utcnow(),
            type=action_type,
            status=status,
            details=details_payload,
        )
        with self._lock:
            self._entries.appendleft(entry)
        return entry

    def list(self) -> List[Dict[str, object]]:
        """Return a copy of the stored entries in newest-first order."""

        with self._lock:
            return [entry.as_dict() for entry in self._entries]

    def extend(self, entries: Iterable[ActivityEntry]) -> None:
        """Insert multiple entries, preserving their order."""

        with self._lock:
            for entry in reversed(list(entries)):
                self._entries.appendleft(entry)

    def clear(self) -> None:
        """Remove all stored entries."""

        with self._lock:
            self._entries.clear()


activity_manager = ActivityManager()


def record_activity(
    action_type: ActivityType,
    status: str,
    *,
    timestamp: Optional[datetime] = None,
    details: Optional[MutableMapping[str, object]] = None,
) -> Dict[str, object]:
    """Record an activity and return its serialised representation."""

    entry = activity_manager.record(
        action_type=action_type,
        status=status,
        timestamp=timestamp,
        details=details,
    )
    return entry.as_dict()
