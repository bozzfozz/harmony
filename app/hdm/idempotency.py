"""Idempotency helpers for the HDM."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import TypeVar

from app.logging import get_logger

from .models import DownloadItem

logger = get_logger("hdm.idempotency")


SQLITE_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""

SQLITE_INSERT = """
INSERT OR IGNORE INTO idempotency_keys (key, status, created_at, updated_at)
VALUES (?, 'in_progress', ?, ?)
"""

SQLITE_SELECT = "SELECT status FROM idempotency_keys WHERE key = ?"

SQLITE_COMPLETE = """
UPDATE idempotency_keys
SET status = 'completed', updated_at = ?
WHERE key = ?
"""

SQLITE_DELETE = "DELETE FROM idempotency_keys WHERE key = ?"

_RETRYABLE_ERROR_FRAGMENTS: tuple[str, ...] = ("locked", "busy")

_T = TypeVar("_T")


@dataclass(slots=True)
class IdempotencyReservation:
    """Result returned when attempting to reserve an idempotency key."""

    acquired: bool
    already_processed: bool
    reason: str | None = None


class IdempotencyStore:
    """Interface for acquiring and releasing idempotency reservations."""

    async def reserve(
        self, item: DownloadItem
    ) -> IdempotencyReservation:  # pragma: no cover - interface
        raise NotImplementedError

    async def release(
        self, item: DownloadItem, *, success: bool
    ) -> None:  # pragma: no cover - interface
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


class SQLiteIdempotencyStore(IdempotencyStore):
    """SQLite backed idempotency store with retry-aware operations."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_attempts: int = 5,
        retry_base_seconds: float = 0.05,
        retry_multiplier: float = 2.0,
        connect_timeout: float = 1.0,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if retry_base_seconds < 0:
            raise ValueError("retry_base_seconds must be non-negative")
        if retry_multiplier < 1:
            raise ValueError("retry_multiplier must be at least 1")
        if connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive")
        self._path = Path(path).expanduser()
        self._max_attempts = int(max_attempts)
        self._retry_base_seconds = float(retry_base_seconds)
        self._retry_multiplier = float(retry_multiplier)
        self._connect_timeout = float(connect_timeout)
        self._initialised = False
        self._init_lock = asyncio.Lock()

    async def reserve(self, item: DownloadItem) -> IdempotencyReservation:
        await self._ensure_initialised()
        key = item.dedupe_key

        def _operation(connection: sqlite3.Connection) -> IdempotencyReservation:
            connection.execute("BEGIN IMMEDIATE")
            try:
                now = time.time()
                cursor = connection.execute(SQLITE_INSERT, (key, now, now))
                if cursor.rowcount == 1:
                    connection.commit()
                    return IdempotencyReservation(acquired=True, already_processed=False)
                cursor = connection.execute(SQLITE_SELECT, (key,))
                row = cursor.fetchone()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            if row is None:
                return IdempotencyReservation(
                    acquired=False,
                    already_processed=False,
                    reason="in_progress",
                )
            if hasattr(row, "keys"):
                raw_status = row["status"]
            else:
                raw_status = row[0]
            status = str(raw_status)
            already_processed = status == "completed"
            reason = "already_completed" if already_processed else "in_progress"
            return IdempotencyReservation(
                acquired=False,
                already_processed=already_processed,
                reason=reason,
            )

        return await self._execute_with_retry(_operation)

    async def release(self, item: DownloadItem, *, success: bool) -> None:
        await self._ensure_initialised()
        key = item.dedupe_key

        def _operation(connection: sqlite3.Connection) -> None:
            connection.execute("BEGIN IMMEDIATE")
            try:
                now = time.time()
                if success:
                    connection.execute(SQLITE_COMPLETE, (now, key))
                else:
                    connection.execute(SQLITE_DELETE, (key,))
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        await self._execute_with_retry(_operation)

    async def _execute_with_retry(
        self, operation: Callable[[sqlite3.Connection], _T]
    ) -> _T:
        attempt = 0
        delay = self._retry_base_seconds
        last_error: Exception | None = None
        while attempt < self._max_attempts:
            attempt += 1
            try:
                return await asyncio.to_thread(self._run_with_connection, operation)
            except sqlite3.OperationalError as exc:
                last_error = exc
                message = str(exc).lower()
                should_retry = any(fragment in message for fragment in _RETRYABLE_ERROR_FRAGMENTS)
                if should_retry and attempt < self._max_attempts:
                    logger.debug(
                        "SQLite idempotency store busy; retrying",
                        extra={
                            "event": "hdm.idempotency.retry",
                            "attempt": attempt,
                            "path": str(self._path),
                            "error": message,
                        },
                    )
                    await asyncio.sleep(delay)
                    delay *= self._retry_multiplier
                    continue
                raise
        assert last_error is not None  # defensive: loop guarantees assignment on failure
        logger.error(
            "Failed to execute SQLite idempotency operation after retries",
            extra={"event": "hdm.idempotency.error", "path": str(self._path)},
            exc_info=last_error,
        )
        raise last_error

    def _run_with_connection(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        connection = sqlite3.connect(
            str(self._path),
            timeout=self._connect_timeout,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        try:
            return operation(connection)
        finally:
            connection.close()

    async def _ensure_initialised(self) -> None:
        if self._initialised:
            return
        async with self._init_lock:
            if self._initialised:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            try:
                await asyncio.to_thread(self._initialise_sync)
            except Exception:
                # Ensure `_initialised` remains ``False`` so subsequent attempts retry.
                raise
            else:
                self._initialised = True

    def _initialise_sync(self) -> None:
        connection = sqlite3.connect(
            str(self._path),
            timeout=self._connect_timeout,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(SQLITE_CREATE_TABLE)
            connection.commit()
        finally:
            connection.close()
