from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download
from app.utils.activity import activity_manager
from app.workers.sync_worker import SyncWorker


class RecordingSoulseekClient:
    def __init__(self) -> None:
        self.download_calls: List[Dict[str, Any]] = []

    async def download(self, payload: Dict[str, Any]) -> None:
        self.download_calls.append(payload)

    async def get_download_status(self) -> List[Dict[str, Any]]:
        return []

    async def cancel_download(self, identifier: str) -> None:  # pragma: no cover - unused
        return None


@pytest.mark.asyncio
async def test_high_priority_jobs_are_processed_first() -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    client = RecordingSoulseekClient()
    worker = SyncWorker(client, concurrency=1)

    with session_scope() as session:
        low = Download(
            filename="low.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=1,
        )
        high = Download(
            filename="high.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=10,
        )
        session.add_all([low, high])
        session.flush()
        low_id = low.id
        high_id = high.id

    await worker.start()

    await worker.enqueue(
        {
            "username": "tester",
            "files": [{"download_id": low_id, "priority": 1}],
            "priority": 1,
        }
    )
    await worker.enqueue(
        {
            "username": "tester",
            "files": [{"download_id": high_id, "priority": 10}],
            "priority": 10,
        }
    )

    await asyncio.sleep(0.05)
    await worker.stop()

    assert len(client.download_calls) >= 2
    first_call = client.download_calls[0]
    first_download_id = first_call["files"][0]["download_id"]
    assert first_download_id == high_id


def test_priority_can_be_updated_via_api(client) -> None:
    with session_scope() as session:
        download = Download(
            filename="adjustable.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=0,
        )
        session.add(download)
        session.flush()
        download_id = download.id

    response = client.patch(
        f"/api/download/{download_id}/priority",
        json={"priority": 7},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["priority"] == 7

    detail_response = client.get(f"/api/download/{download_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["priority"] == 7
    assert detail["status"] == "queued"
