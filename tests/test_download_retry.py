from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download, QueueJobStatus
from app.orchestrator.handlers import (
    RetryHandlerDeps,
    SyncRetryPolicy,
    calculate_retry_backoff_seconds,
    handle_retry,
    load_sync_retry_policy,
)
from app.services.retry_policy_provider import get_retry_policy_provider
from app.utils.activity import activity_manager
from app.utils.events import DOWNLOAD_RETRY_FAILED, DOWNLOAD_RETRY_SCHEDULED
from app.workers.persistence import QueueJobDTO
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

    async def cancel_download(
        self, identifier: str
    ) -> None:  # pragma: no cover - unused
        return None


@pytest.mark.asyncio
async def test_retry_schedule_sets_next_retry_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        "files": [
            {
                "download_id": download_id,
                "priority": 5,
                "filename": "priority-track.mp3",
            }
        ],
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

    async def submit_sync_job(
        payload: Dict[str, Any],
        *,
        priority: int | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        captured.append(
            {
                "payload": dict(payload),
                "priority": priority,
                "key": idempotency_key,
            }
        )

    deps = RetryHandlerDeps(
        submit_sync_job=submit_sync_job,
        retry_policy=SyncRetryPolicy(max_attempts=5, base_seconds=1.0, jitter_pct=0.0),
        rng=random.Random(0),
        auto_reschedule=False,
    )

    job = QueueJobDTO(
        id=1,
        type="retry",
        payload={"batch_limit": 5, "scan_interval": 0.0},
        priority=0,
        attempts=0,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key="retry-scan",
        last_error=None,
        result_payload=None,
        lease_timeout_seconds=60,
    )

    result = await handle_retry(job, deps)

    assert len(captured) == 1
    submission = captured[0]
    payload = submission["payload"]
    assert payload["username"] == "tester"
    assert payload["files"][0]["download_id"] == download_id
    assert payload["idempotency_key"] == f"retry:{download_id}"
    assert submission["key"] == f"retry:{download_id}"
    assert result["scheduled"] == [{"download_id": download_id, "retry_count": 1}]

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "queued"
        assert refreshed.next_retry_at is None


@pytest.mark.asyncio
async def test_worker_refreshes_retry_policy_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = get_retry_policy_provider()
    provider.invalidate()
    monkeypatch.setenv("RETRY_POLICY_RELOAD_S", "0")
    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("RETRY_BASE_SECONDS", "1")
    monkeypatch.setenv("RETRY_JITTER_PCT", "0")

    worker = SyncWorker(FlakySoulseekClient(failures=0), concurrency=1)

    assert worker.retry_policy.max_attempts == 2
    assert worker.retry_policy.base_seconds == 1.0

    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("RETRY_BASE_SECONDS", "3")
    monkeypatch.setenv("RETRY_JITTER_PCT", "10")

    worker.refresh_retry_policy()

    assert worker.retry_policy.max_attempts == 5
    assert worker.retry_policy.base_seconds == 3.0
    assert worker.retry_policy.jitter_pct == 0.1


def test_load_sync_retry_policy_uses_live_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = get_retry_policy_provider()
    provider.invalidate()
    monkeypatch.setenv("RETRY_POLICY_RELOAD_S", "0")
    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("RETRY_BASE_SECONDS", "2")
    monkeypatch.setenv("RETRY_JITTER_PCT", "5")

    initial = load_sync_retry_policy()
    assert initial.max_attempts == 4
    assert initial.base_seconds == 2.0
    assert initial.jitter_pct == pytest.approx(0.05)

    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "9")
    monkeypatch.setenv("RETRY_BASE_SECONDS", "12")
    monkeypatch.setenv("RETRY_JITTER_PCT", "15")
    provider.invalidate()

    updated = load_sync_retry_policy()

    assert updated.max_attempts == 9
    assert updated.base_seconds == 12.0
    assert updated.jitter_pct == pytest.approx(0.15)
    assert updated != initial


@pytest.mark.asyncio
async def test_handle_retry_failure_sets_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("RETRY_BASE_SECONDS", "2")
    monkeypatch.setenv("RETRY_JITTER_PCT", "0")

    with session_scope() as session:
        download = Download(
            filename="retry-failure.mp3",
            state="failed",
            progress=0.0,
            priority=2,
            username="tester",
            retry_count=2,
            next_retry_at=datetime.utcnow() - timedelta(seconds=30),
            request_payload={
                "file": {"filename": "retry-failure.mp3", "priority": 2},
                "username": "tester",
                "priority": 2,
            },
        )
        session.add(download)
        session.flush()
        payload = dict(download.request_payload or {})
        payload.setdefault("file", {})["download_id"] = download.id
        download.request_payload = payload
        session.add(download)
        download_id = download.id

    async def failing_submit(
        payload: Dict[str, Any],
        *,
        priority: int | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        raise RuntimeError("queue unavailable")

    retry_policy = SyncRetryPolicy(max_attempts=5, base_seconds=2.0, jitter_pct=0.0)
    rng_seed = 1
    deps = RetryHandlerDeps(
        submit_sync_job=failing_submit,
        retry_policy=retry_policy,
        rng=random.Random(rng_seed),
        auto_reschedule=False,
    )

    job = QueueJobDTO(
        id=2,
        type="retry",
        payload={"batch_limit": 5, "scan_interval": 0.0},
        priority=0,
        attempts=0,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key="retry-scan",
        last_error=None,
        result_payload=None,
        lease_timeout_seconds=60,
    )

    before = datetime.utcnow()
    result = await handle_retry(job, deps)

    assert result["failed"] == [
        {"download_id": download_id, "retry_count": 2, "error": "queue unavailable"}
    ]

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "failed"
        assert refreshed.next_retry_at is not None
        assert refreshed.next_retry_at > before
        delay = (refreshed.next_retry_at - before).total_seconds()
        expected_delay = calculate_retry_backoff_seconds(
            2, retry_policy, random.Random(rng_seed)
        )
        assert pytest.approx(delay, rel=0.2) == expected_delay

    events = [entry["status"] for entry in activity_manager.list()]
    assert DOWNLOAD_RETRY_FAILED in events


@pytest.mark.asyncio
async def test_dlq_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    provider = get_retry_policy_provider()
    provider.invalidate()
    monkeypatch.setenv("RETRY_POLICY_RELOAD_S", "0")
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
        "files": [
            {
                "download_id": download_id,
                "priority": 1,
                "filename": "stubborn-track.mp3",
            }
        ],
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
