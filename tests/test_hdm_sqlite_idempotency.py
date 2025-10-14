import asyncio
from pathlib import Path
import sqlite3
import types
from uuid import uuid4

import aiosqlite
import pytest

from app.hdm.idempotency import SQLiteIdempotencyStore
from app.hdm.models import DownloadItem


def _make_item(*, batch: str = "batch", dedupe: str | None = None) -> DownloadItem:
    key = dedupe or uuid4().hex
    return DownloadItem(
        batch_id=batch,
        item_id=uuid4().hex,
        artist="Artist",
        title="Title",
        album=None,
        isrc=None,
        requested_by="tester",
        priority=0,
        dedupe_key=key,
        index=0,
    )


@pytest.mark.asyncio()
async def test_sqlite_store_handles_reserve_and_release(idempotency_db_path: Path) -> None:
    store = SQLiteIdempotencyStore(idempotency_db_path)
    item = _make_item(dedupe="same-key")

    reservation = await store.reserve(item)
    assert reservation.acquired is True
    assert reservation.already_processed is False

    duplicate = await store.reserve(item)
    assert duplicate.acquired is False
    assert duplicate.already_processed is False
    assert duplicate.reason == "in_progress"

    await store.release(item, success=False)

    reservation_again = await store.reserve(item)
    assert reservation_again.acquired is True

    await store.release(item, success=True)

    final_attempt = await store.reserve(item)
    assert final_attempt.acquired is False
    assert final_attempt.already_processed is True
    assert final_attempt.reason == "already_completed"


@pytest.mark.asyncio()
async def test_sqlite_store_retries_when_database_locked(idempotency_db_path: Path) -> None:
    store = SQLiteIdempotencyStore(
        idempotency_db_path,
        max_attempts=5,
        retry_base_seconds=0.01,
        retry_multiplier=2.0,
    )

    warm_item = _make_item()
    await store.reserve(warm_item)
    await store.release(warm_item, success=False)

    connection = sqlite3.connect(idempotency_db_path)
    connection.execute("BEGIN EXCLUSIVE")

    async def _release_later() -> None:
        try:
            await asyncio.sleep(0.05)
            connection.commit()
        finally:
            connection.close()

    release_task = asyncio.create_task(_release_later())
    item = _make_item(dedupe="locked-key")
    reservation = None
    try:
        reservation = await store.reserve(item)
        assert reservation.acquired is True
    finally:
        await release_task
        if reservation is not None and reservation.acquired:
            await store.release(item, success=False)


@pytest.mark.asyncio()
async def test_sqlite_store_retries_when_database_busy(idempotency_db_path: Path) -> None:
    store = SQLiteIdempotencyStore(
        idempotency_db_path,
        max_attempts=3,
        retry_base_seconds=0.0,
        retry_multiplier=1.0,
    )

    attempts = 0
    real_connect = store._connect

    async def flaky_connect(self: SQLiteIdempotencyStore):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is busy")
        return await real_connect()

    store._connect = types.MethodType(flaky_connect, store)

    item = _make_item(dedupe="busy-key")
    reservation = await store.reserve(item)

    assert attempts == 2
    assert reservation.acquired is True

    await store.release(item, success=False)


@pytest.mark.asyncio()
async def test_sqlite_store_initialisation_failure_keeps_retrying(
    monkeypatch: pytest.MonkeyPatch, idempotency_db_path: Path
) -> None:
    store = SQLiteIdempotencyStore(idempotency_db_path)
    attempts = 0
    real_connect = aiosqlite.connect

    async def flaky_connect(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("disk I/O error")
        return await real_connect(*args, **kwargs)

    monkeypatch.setattr("app.hdm.idempotency.aiosqlite.connect", flaky_connect)

    failing_item = _make_item(dedupe="init-failure")
    with pytest.raises(sqlite3.OperationalError):
        await store.reserve(failing_item)

    assert store._initialised is False  # noqa: SLF001 - verifying retry guard

    successful_item = _make_item(dedupe="init-success")
    reservation = await store.reserve(successful_item)

    assert attempts >= 2
    assert reservation.acquired is True
    assert store._initialised is True

    await store.release(successful_item, success=False)
