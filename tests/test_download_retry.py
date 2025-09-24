from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download
from app.utils.events import (
    DOWNLOAD_RETRY_COMPLETED,
    DOWNLOAD_RETRY_FAILED,
    DOWNLOAD_RETRY_SCHEDULED,
)
from app.utils.activity import activity_manager
from app.workers.sync_worker import MAX_RETRY_ATTEMPTS, RETRY_BACKOFF, SyncWorker


class FlakySoulseekClient:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.download_calls: List[Dict[str, Any]] = []

    async def download(self, payload: Dict[str, Any]) -> None:
        self.download_calls.append(payload)
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("simulated failure")

    async def get_download_status(self) -> List[Dict[str, Any]]:
        return []

    async def cancel_download(self, identifier: str) -> None:  # pragma: no cover - unused
        return None


@pytest.mark.asyncio
async def test_retry_is_scheduled_and_completed(monkeypatch) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    monkeypatch.setattr(
        "app.workers.sync_worker.RETRY_BACKOFF",
        tuple(0.01 for _ in RETRY_BACKOFF),
    )

    client = FlakySoulseekClient(failures=1)
    worker = SyncWorker(client, concurrency=1)

    with session_scope() as session:
        download = Download(
            filename="priority-track.mp3",
            state="queued",
            progress=0.0,
            priority=5,
        )
        session.add(download)
        session.flush()
        download_id = download.id

    job = {
        "username": "tester",
        "files": [{"download_id": download_id, "priority": 5}],
        "priority": 5,
    }

    await worker.enqueue(job)
    await asyncio.sleep(0.05)

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in entries]
    assert DOWNLOAD_RETRY_SCHEDULED in statuses
    assert DOWNLOAD_RETRY_COMPLETED in statuses

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.priority == 5
        assert refreshed.request_payload.get("retry_attempts") is None

    assert len(client.download_calls) >= 2


@pytest.mark.asyncio
async def test_retry_fails_after_max_attempts(monkeypatch) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    monkeypatch.setattr(
        "app.workers.sync_worker.RETRY_BACKOFF",
        tuple(0.01 for _ in RETRY_BACKOFF),
    )
    monkeypatch.setattr(
        "app.workers.sync_worker.MAX_RETRY_ATTEMPTS",
        MAX_RETRY_ATTEMPTS,
    )

    client = FlakySoulseekClient(failures=MAX_RETRY_ATTEMPTS + 1)
    worker = SyncWorker(client, concurrency=1)

    with session_scope() as session:
        download = Download(
            filename="stubborn-track.mp3",
            state="queued",
            progress=0.0,
            priority=1,
        )
        session.add(download)
        session.flush()
        download_id = download.id

    job = {
        "username": "tester",
        "files": [{"download_id": download_id, "priority": 1}],
        "priority": 1,
    }

    await worker.enqueue(job)
    await asyncio.sleep(0.1)

    entries = activity_manager.list()
    statuses = [entry["status"] for entry in entries]
    assert DOWNLOAD_RETRY_FAILED in statuses

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "failed"
        assert refreshed.request_payload.get("retry_attempts") == MAX_RETRY_ATTEMPTS

    assert len(client.download_calls) >= MAX_RETRY_ATTEMPTS + 1
