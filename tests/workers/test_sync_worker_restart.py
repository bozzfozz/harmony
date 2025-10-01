"""Regression tests for SyncWorker lifecycle behaviour."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download
from app.utils.activity import activity_manager
from app.workers.sync_worker import SyncWorker


class RecordingSoulseekClient:
    """Minimal Soulseek client stub recording download payloads."""

    def __init__(self) -> None:
        self.download_calls: List[Dict[str, Any]] = []

    async def download(self, payload: Dict[str, Any]) -> None:
        self.download_calls.append(payload)

    async def get_download_status(self) -> List[Dict[str, Any]]:
        return []

    async def cancel_download(self, identifier: str) -> None:  # pragma: no cover - unused
        return None


@pytest.mark.asyncio
async def test_sync_worker_processes_jobs_after_restart() -> None:
    """Ensure stale shutdown sentinels do not abort restarted workers."""

    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    client = RecordingSoulseekClient()
    worker = SyncWorker(client, concurrency=1)

    with session_scope() as session:
        download = Download(
            filename="restart.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=1,
        )
        session.add(download)
        session.flush()
        download_id = download.id

    try:
        await worker.start()
        await asyncio.sleep(0)  # Allow background tasks to start.
        await worker.stop()

        assert worker.queue.empty(), "Shutdown should consume sentinel values"
        assert worker._poll_task is None

        await worker.start()
        await worker.enqueue(
            {
                "username": "tester",
                "files": [{"download_id": download_id, "priority": 1}],
                "priority": 1,
            }
        )

        async def wait_for_download() -> None:
            while not client.download_calls:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_download(), timeout=1.0)
    finally:
        await worker.stop()

    assert len(client.download_calls) == 1
