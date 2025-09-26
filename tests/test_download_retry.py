from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest
import random

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download
from app.utils.activity import activity_manager
from app.utils.events import (
    DOWNLOAD_RETRY_FAILED,
    DOWNLOAD_RETRY_SCHEDULED,
)
from app.workers.retry_scheduler import RetryScheduler
from app.workers.sync_worker import (
    DownloadJobError,
    RetryConfig,
    SyncWorker,
    _calculate_backoff_seconds,
)


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
async def test_retry_schedule_sets_next_retry_at(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("RETRY_BASE_SECONDS", "1")
    monkeypatch.setenv("RETRY_JITTER_PCT", "0")

    client = FlakySoulseekClient(failures=1)
    worker = SyncWorker(client, concurrency=1)

    with session_scope() as session:
        download = Download(
            filename="priority-track.mp3",
            state="queued",
            progress=0.0,
            priority=5,
            username="tester",
        )
        session.add(download)
        session.flush()
        download_id = download.id

    job = {
        "username": "tester",
        "files": [{"download_id": download_id, "priority": 5, "filename": "priority-track.mp3"}],
        "priority": 5,
    }

    try:
        await worker.enqueue(job)
    except DownloadJobError:
        pass

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.retry_count == 1
        assert refreshed.state == "failed"
        assert refreshed.last_error is not None
        assert refreshed.next_retry_at is not None
        assert refreshed.next_retry_at > datetime.utcnow()

    events = [entry["status"] for entry in activity_manager.list()]
    assert DOWNLOAD_RETRY_SCHEDULED in events
    assert len(client.download_calls) == 1
    recorded = client.download_calls[0]
    assert recorded["username"] == "tester"
    assert recorded["files"][0]["download_id"] == download_id


@pytest.mark.asyncio
async def test_retry_enqueues_when_due(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("RETRY_BASE_SECONDS", "1")
    monkeypatch.setenv("RETRY_JITTER_PCT", "0")

    with session_scope() as session:
        download = Download(
            filename="stalled.mp3",
            state="failed",
            progress=0.0,
            priority=4,
            username="tester",
            retry_count=1,
            next_retry_at=datetime.utcnow() - timedelta(seconds=5),
            request_payload={
                "file": {"filename": "stalled.mp3", "priority": 4},
                "username": "tester",
                "priority": 4,
            },
        )
        session.add(download)
        session.flush()
        payload = dict(download.request_payload or {})
        payload.setdefault("file", {})["download_id"] = download.id
        download.request_payload = payload
        session.add(download)
        download_id = download.id

    captured: List[Dict[str, Any]] = []

    class RecordingWorker:
        async def enqueue(self, job: Dict[str, Any]) -> None:
            captured.append(job)

    scheduler = RetryScheduler(
        RecordingWorker(),
        retry_config=RetryConfig(max_attempts=5, base_seconds=1.0, jitter_pct=0.0),
    )

    await scheduler._scan_and_enqueue()

    assert len(captured) == 1
    job = captured[0]
    assert job["username"] == "tester"
    assert job["files"][0]["download_id"] == download_id

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "queued"
        assert refreshed.next_retry_at is None


@pytest.mark.asyncio
async def test_dlq_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("RETRY_BASE_SECONDS", "1")
    monkeypatch.setenv("RETRY_JITTER_PCT", "0")

    client = FlakySoulseekClient(failures=2)
    worker = SyncWorker(client, concurrency=1)

    with session_scope() as session:
        download = Download(
            filename="stubborn-track.mp3",
            state="queued",
            progress=0.0,
            priority=1,
            username="tester",
        )
        session.add(download)
        session.flush()
        download_id = download.id

    job = {
        "username": "tester",
        "files": [{"download_id": download_id, "priority": 1, "filename": "stubborn-track.mp3"}],
        "priority": 1,
    }

    for _ in range(2):
        try:
            await worker.enqueue(job)
        except DownloadJobError:
            pass

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "dead_letter"
        assert refreshed.retry_count == 2
        assert refreshed.next_retry_at is None
        assert refreshed.last_error is not None

    events = [entry["status"] for entry in activity_manager.list()]
    assert DOWNLOAD_RETRY_FAILED in events


def test_jitter_within_bounds() -> None:
    config = RetryConfig(max_attempts=5, base_seconds=10.0, jitter_pct=0.2)
    rng = random.Random(42)
    base_delay = config.base_seconds * (2 ** min(3, 6))
    lower = base_delay * (1 - config.jitter_pct)
    upper = base_delay * (1 + config.jitter_pct)
    for _ in range(5):
        delay = _calculate_backoff_seconds(3, config, rng)
        assert lower <= delay <= upper


def test_requeue_endpoint_guards_on_dead_letter(client) -> None:
    payload = {
        "username": "tester",
        "files": [
            {
                "id": 1,
                "filename": "song.flac",
                "priority": 3,
            }
        ],
    }

    response = client.post("/soulseek/download", json=payload)
    assert response.status_code == 200
    download_id = response.json()["detail"]["downloads"][0]["id"]

    with session_scope() as session:
        record = session.get(Download, download_id)
        assert record is not None
        record.state = "dead_letter"
        record.retry_count = 5
        record.next_retry_at = None
        session.add(record)

    requeue = client.post(f"/soulseek/downloads/{download_id}/requeue")
    assert requeue.status_code == 409
