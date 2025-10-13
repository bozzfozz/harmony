"""Idempotency helpers for the HDM."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import TypeVar

import aiosqlite
from aiosqlite import OperationalError as AioSqliteOperationalError

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

_LOCK_ERROR_FRAGMENT = "locked"

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

        async def _operation(connection: aiosqlite.Connection) -> IdempotencyReservation:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                now = time.time()
                cursor = await connection.execute(SQLITE_INSERT, (key, now, now))
                if cursor.rowcount == 1:
                    await connection.commit()
                    return IdempotencyReservation(acquired=True, already_processed=False)
                cursor = await connection.execute(SQLITE_SELECT, (key,))
                row = await cursor.fetchone()
                await connection.commit()
            except Exception:
                await connection.rollback()
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

        async def _operation(connection: aiosqlite.Connection) -> None:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                now = time.time()
                if success:
                    await connection.execute(SQLITE_COMPLETE, (now, key))
                else:
                    await connection.execute(SQLITE_DELETE, (key,))
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

        await self._execute_with_retry(_operation)

    async def _execute_with_retry(
        self, operation: Callable[[aiosqlite.Connection], Awaitable[_T]]
    ) -> _T:
        attempt = 0
        delay = self._retry_base_seconds
        last_error: Exception | None = None
        while attempt < self._max_attempts:
            attempt += 1
            connection: aiosqlite.Connection | None = None
            try:
                connection = await self._connect()
                return await operation(connection)
            except (sqlite3.OperationalError, AioSqliteOperationalError) as exc:
                last_error = exc
                message = str(exc).lower()
                if _LOCK_ERROR_FRAGMENT in message and attempt < self._max_attempts:
                    logger.debug(
                        "SQLite idempotency store busy; retrying",
                        extra={
                            "event": "hdm.idempotency.retry",
                            "attempt": attempt,
                            "path": str(self._path),
                        },
                    )
                    await asyncio.sleep(delay)
                    delay *= self._retry_multiplier
                    continue
                raise
            finally:
                if connection is not None:
                    await connection.close()
        assert last_error is not None  # defensive: loop guarantees assignment on failure
        logger.error(
            "Failed to execute SQLite idempotency operation after retries",
            extra={"event": "hdm.idempotency.error", "path": str(self._path)},
            exc_info=last_error,
        )
        raise last_error

    async def _connect(self) -> aiosqlite.Connection:
        connection = await aiosqlite.connect(
            str(self._path),
            timeout=self._connect_timeout,
            isolation_level=None,
        )
        connection.row_factory = aiosqlite.Row
        return connection

    async def _ensure_initialised(self) -> None:
        if self._initialised:
            return
        async with self._init_lock:
            if self._initialised:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = await aiosqlite.connect(str(self._path))
            try:
                await connection.execute("PRAGMA journal_mode=WAL")
                await connection.execute(SQLITE_CREATE_TABLE)
                await connection.commit()
            finally:
                await connection.close()
            self._initialised = True
