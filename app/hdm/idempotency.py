"""Idempotency helpers for the HDM."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .models import DownloadItem


@dataclass(slots=True)
class IdempotencyReservation:
    """Result returned when attempting to reserve an idempotency key."""

    acquired: bool
    already_processed: bool
    reason: str | None = None


class IdempotencyStore:
    """Interface for acquiring and releasing idempotency reservations."""

    async def reserve(self, item: DownloadItem) -> IdempotencyReservation:  # pragma: no cover - interface
        raise NotImplementedError

    async def release(self, item: DownloadItem, *, success: bool) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class InMemoryIdempotencyStore(IdempotencyStore):
    """Simple in-memory idempotency store suitable for tests and local runs."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._in_progress: set[str] = set()
        self._completed: set[str] = set()

    async def reserve(self, item: DownloadItem) -> IdempotencyReservation:
        key = item.dedupe_key
        async with self._lock:
            if key in self._completed:
                return IdempotencyReservation(
                    acquired=False,
                    already_processed=True,
                    reason="already_completed",
                )
            if key in self._in_progress:
                return IdempotencyReservation(
                    acquired=False,
                    already_processed=False,
                    reason="in_progress",
                )
            self._in_progress.add(key)
        return IdempotencyReservation(acquired=True, already_processed=False)

    async def release(self, item: DownloadItem, *, success: bool) -> None:
        key = item.dedupe_key
        async with self._lock:
            self._in_progress.discard(key)
            if success:
                self._completed.add(key)
