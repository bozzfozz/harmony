from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
import dataclasses
import logging
from typing import Any, Callable, Iterable, Mapping

import pytest
from sqlalchemy import select

from app.config import ExternalCallPolicy, settings
from app.core.matching_engine import MusicMatchingEngine
from app.models import QueueJobStatus
from app.orchestrator.dispatcher import Dispatcher, default_handlers
from app.orchestrator.handlers import MatchingHandlerDeps, SyncHandlerDeps, SyncRetryPolicy
from app.workers import persistence
from app.utils.activity import activity_manager
from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download, Match


class StubScheduler:
    def __init__(self, batches: Iterable[Iterable[persistence.QueueJobDTO]]) -> None:
        self._batches = [list(batch) for batch in batches]
        self.poll_interval = 0.01

    def lease_ready_jobs(self) -> list[persistence.QueueJobDTO]:
        if not self._batches:
            return []
        return list(self._batches.pop(0))


class StubPersistence:
    def __init__(self) -> None:
        self.complete_calls: list[tuple[int, str, Mapping[str, Any] | None]] = []
        self.fail_calls: list[tuple[int, str, str | None, int | None]] = []
        self.dlq_calls: list[tuple[int, str, str, Mapping[str, Any] | None]] = []
        self.heartbeat_calls: list[tuple[int, str, int | None]] = []

    def complete(
        self,
        job_id: int,
        *,
        job_type: str,
        result_payload: Mapping[str, Any] | None = None,
    ) -> bool:
        self.complete_calls.append((job_id, job_type, result_payload))
        return True

    def fail(
        self,
        job_id: int,
        *,
        job_type: str,
        error: str | None = None,
        retry_in: int | None = None,
        available_at: datetime | None = None,
    ) -> bool:
        self.fail_calls.append((job_id, job_type, error, retry_in))
        return True

    def to_dlq(
        self,
        job_id: int,
        *,
        job_type: str,
        reason: str,
        payload: Mapping[str, Any] | None = None,
    ) -> bool:
        self.dlq_calls.append((job_id, job_type, reason, payload))
        return True

    def heartbeat(
        self,
        job_id: int,
        *,
        job_type: str,
        lease_seconds: int | None = None,
    ) -> bool:
        self.heartbeat_calls.append((job_id, job_type, lease_seconds))
        return True


class LeaseLosingStubPersistence(StubPersistence):
    """Persistence stub that reports a single heartbeat failure."""

    def __init__(
        self,
        *,
        on_lease_lost: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_lease_lost = on_lease_lost
        self._lease_lost_reported = False

    def heartbeat(
        self,
        job_id: int,
        *,
        job_type: str,
        lease_seconds: int | None = None,
    ) -> bool:
        self.heartbeat_calls.append((job_id, job_type, lease_seconds))
        if not self._lease_lost_reported:
            self._lease_lost_reported = True
            if self._on_lease_lost is not None:
                self._on_lease_lost()
            return False
        return True


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Mapping[str, Any]]]:
    events: list[tuple[str, Mapping[str, Any]]] = []

    def recorder(logger: Any, event: str, /, **fields: Any) -> None:  # noqa: ANN401 - test helper
        events.append((event, dict(fields)))

    monkeypatch.setattr("app.orchestrator.events.log_event", recorder)
    monkeypatch.setattr("app.orchestrator.events.increment_counter", lambda *args, **kwargs: 0)
    return events


async def _wait_for_heartbeat(storage: StubPersistence, interval: float = 0.01) -> None:
    while not storage.heartbeat_calls:
        await asyncio.sleep(interval)


def make_job(
    job_id: int,
    job_type: str,
    *,
    attempts: int,
    lease_timeout: int = 2,
    payload: Mapping[str, Any] | None = None,
) -> persistence.QueueJobDTO:
    now = datetime.utcnow()
    return persistence.QueueJobDTO(
        id=job_id,
        type=job_type,
        payload=dict(payload or {}),
        priority=10,
        attempts=attempts,
        available_at=now,
        lease_expires_at=now + timedelta(seconds=lease_timeout),
        status=QueueJobStatus.LEASED,
        idempotency_key=None,
        last_error=None,
        result_payload=None,
        lease_timeout_seconds=lease_timeout,
    )


@pytest.mark.asyncio
async def test_dispatcher_executes_job_and_marks_complete(
    caplog: pytest.LogCaptureFixture, captured_events: list[tuple[str, Mapping[str, Any]]]
) -> None:
    caplog.set_level("INFO", logger="app.orchestrator.dispatcher")
    job = make_job(1, "sync", attempts=1, payload={"foo": "bar"})
    scheduler = StubScheduler([[job], []])
    storage = StubPersistence()
    executed = asyncio.Event()

    async def handler(record: persistence.QueueJobDTO) -> Mapping[str, Any]:
        executed.set()
        return {"handled": record.id}

    dispatcher = Dispatcher(scheduler, {"sync": handler}, persistence_module=storage)

    task = asyncio.create_task(dispatcher.run())
    await asyncio.wait_for(executed.wait(), timeout=1)
    dispatcher.request_stop()
    await asyncio.wait_for(task, timeout=1)

    assert storage.complete_calls == [(1, "sync", {"handled": 1})]
    assert storage.fail_calls == []
    assert storage.dlq_calls == []

    commit_events = [
        payload for event_name, payload in captured_events if event_name == "orchestrator.commit"
    ]
    assert commit_events
    payload = commit_events[-1]
    assert payload["job_type"] == "sync"
    assert payload["entity_id"] == "1"
    assert payload["status"] == "succeeded"
    assert payload["attempts"] == 1

    heartbeat_events = [
        payload for event_name, payload in captured_events if event_name == "orchestrator.heartbeat"
    ]
    assert heartbeat_events
    assert heartbeat_events[-1]["status"] == "stopped"


@pytest.mark.asyncio
async def test_dispatcher_drains_queue_under_mixed_load() -> None:
    jobs = [
        [
            make_job(1, "sync", attempts=0, lease_timeout=5),
            make_job(2, "matching", attempts=0, lease_timeout=5),
        ],
        [make_job(3, "sync", attempts=0, lease_timeout=5)],
        [],
    ]
    scheduler = StubScheduler(jobs)
    storage = StubPersistence()
    completions: list[int] = []

    async def sync_handler(job: persistence.QueueJobDTO) -> Mapping[str, Any]:
        await asyncio.sleep(0)
        completions.append(job.id)
        return {"ok": True}

    async def matching_handler(job: persistence.QueueJobDTO) -> Mapping[str, Any]:
        await asyncio.sleep(0)
        completions.append(job.id)
        return {"ok": True}

    dispatcher = Dispatcher(
        scheduler,
        {"sync": sync_handler, "matching": matching_handler},
        persistence_module=storage,
        global_concurrency=2,
        pool_concurrency={"sync": 2, "matching": 1},
    )

    task = asyncio.create_task(dispatcher.run())
    try:
        await asyncio.wait_for(_wait_for_completions(storage, expected=3), timeout=1)
    finally:
        dispatcher.request_stop()
        await asyncio.wait_for(task, timeout=1)

    assert sorted(job_id for job_id, *_ in storage.complete_calls) == [1, 2, 3]
    assert sorted(completions) == [1, 2, 3]
    assert scheduler.lease_ready_jobs() == []


async def _wait_for_completions(storage: StubPersistence, *, expected: int) -> None:
    while len(storage.complete_calls) < expected:
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_dispatcher_heartbeat_interval_respects_visibility() -> None:
    async def handler(record: persistence.QueueJobDTO) -> Mapping[str, Any]:
        return {}

    scheduler = StubScheduler([[]])
    storage = StubPersistence()

    custom_config = dataclasses.replace(
        settings.orchestrator,
        visibility_timeout_s=120,
        heartbeat_s=30,
    )
    dispatcher = Dispatcher(
        scheduler,
        {"sync": handler},
        persistence_module=storage,
        orchestrator_config=custom_config,
    )

    job_with_lease = make_job(99, "sync", attempts=1, lease_timeout=40)
    interval_with_lease = dispatcher._heartbeat_interval(job_with_lease)
    assert interval_with_lease == 20

    job_without_lease = make_job(100, "sync", attempts=1, lease_timeout=40)
    job_without_lease.lease_timeout_seconds = None
    interval_without_lease = dispatcher._heartbeat_interval(job_without_lease)
    assert interval_without_lease == 30


@pytest.mark.asyncio
async def test_dispatcher_retries_with_backoff(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    captured_events: list[tuple[str, Mapping[str, Any]]],
) -> None:
    caplog.set_level("INFO", logger="app.orchestrator.dispatcher")
    monkeypatch.setenv("EXTERNAL_RETRY_MAX", "3")
    monkeypatch.setenv("EXTERNAL_BACKOFF_BASE_MS", "1000")
    monkeypatch.setenv("EXTERNAL_JITTER_PCT", "0")

    job = make_job(2, "sync", attempts=1)
    scheduler = StubScheduler([[job], []])
    storage = StubPersistence()
    failed = asyncio.Event()

    async def handler(_: persistence.QueueJobDTO) -> Mapping[str, Any]:
        raise RuntimeError("transient failure")

    def fail_hook(*args: Any, **kwargs: Any) -> bool:
        result = StubPersistence.fail(storage, *args, **kwargs)
        failed.set()
        return result

    storage.fail = fail_hook  # type: ignore[assignment]

    dispatcher = Dispatcher(scheduler, {"sync": handler}, persistence_module=storage)

    task = asyncio.create_task(dispatcher.run())
    await asyncio.wait_for(failed.wait(), timeout=1)
    dispatcher.request_stop()
    await asyncio.wait_for(task, timeout=1)

    assert storage.fail_calls == [(2, "sync", "transient failure", 1)]
    assert storage.dlq_calls == []
    assert storage.complete_calls == []

    commit_events = [
        payload for event_name, payload in captured_events if event_name == "orchestrator.commit"
    ]
    assert commit_events
    payload = commit_events[-1]
    assert payload["status"] == "retry"
    assert payload["retry_in"] == 1


@pytest.mark.asyncio
async def test_dispatcher_moves_job_to_dlq_when_retries_exhausted(
    caplog: pytest.LogCaptureFixture,
    captured_events: list[tuple[str, Mapping[str, Any]]],
) -> None:
    caplog.set_level("INFO", logger="app.orchestrator.dispatcher")
    policy = ExternalCallPolicy(
        timeout_ms=10_000,
        retry_max=2,
        backoff_base_ms=100,
        jitter_pct=0.0,
    )

    job = make_job(3, "sync", attempts=2)
    scheduler = StubScheduler([[job], []])
    storage = StubPersistence()
    dead_lettered = asyncio.Event()

    async def handler(_: persistence.QueueJobDTO) -> Mapping[str, Any]:
        raise RuntimeError("dependency failed")

    def dlq_hook(*args: Any, **kwargs: Any) -> bool:
        result = StubPersistence.to_dlq(storage, *args, **kwargs)
        dead_lettered.set()
        return result

    storage.to_dlq = dlq_hook  # type: ignore[assignment]

    dispatcher = Dispatcher(
        scheduler,
        {"sync": handler},
        persistence_module=storage,
        external_policy=policy,
    )

    task = asyncio.create_task(dispatcher.run())
    await asyncio.wait_for(dead_lettered.wait(), timeout=1)
    dispatcher.request_stop()
    await asyncio.wait_for(task, timeout=1)

    assert storage.dlq_calls == [
        (
            3,
            "sync",
            "max_retries_exhausted",
            {"error": "dependency failed", "attempts": 2},
        )
    ]
    assert storage.fail_calls == []
    assert storage.complete_calls == []

    dlq_events = [
        payload for event_name, payload in captured_events if event_name == "orchestrator.dlq"
    ]
    assert dlq_events
    payload = dlq_events[-1]
    assert payload["status"] == "dead_letter"
    assert payload["stop_reason"] == "max_retries_exhausted"


@pytest.mark.asyncio
async def test_dispatcher_stops_job_when_lease_lost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="app.orchestrator.dispatcher")
    logging.getLogger("app.orchestrator.dispatcher").disabled = False

    job = make_job(4, "sync", attempts=1, lease_timeout=2)
    scheduler = StubScheduler([[job], []])

    handler_started = asyncio.Event()
    handler_cancelled = asyncio.Event()
    handler_release = asyncio.Event()

    storage = LeaseLosingStubPersistence()

    async def handler(_: persistence.QueueJobDTO) -> Mapping[str, Any]:
        handler_started.set()
        try:
            await handler_release.wait()
        except asyncio.CancelledError:
            handler_cancelled.set()
            raise
        return {"handled": "unexpected"}

    dispatcher = Dispatcher(scheduler, {"sync": handler}, persistence_module=storage)

    run_task = asyncio.create_task(dispatcher.run())

    try:
        await asyncio.wait_for(handler_started.wait(), timeout=1)
        await asyncio.wait_for(_wait_for_heartbeat(storage), timeout=2)
        await asyncio.wait_for(handler_cancelled.wait(), timeout=2)
    finally:
        handler_release.set()
        dispatcher.request_stop()
        await asyncio.wait_for(run_task, timeout=2)

    assert storage.complete_calls == []
    assert storage.fail_calls == []
    assert storage.dlq_calls == []

    heartbeat_records = [
        record for record in caplog.records if record.getMessage() == "orchestrator.heartbeat"
    ]
    assert heartbeat_records, "Expected lease loss heartbeat log"
    heartbeat_statuses = [record.status for record in heartbeat_records]
    assert heartbeat_statuses[-1] == "aborted"
    assert "lost" in heartbeat_statuses
    assert heartbeat_records[-1].job_type == "sync"

    assert not any(record.getMessage() == "orchestrator.commit" for record in caplog.records)


@pytest.mark.asyncio
async def test_handle_failure_skips_when_lease_lost(
    captured_events: list[tuple[str, Mapping[str, Any]]],
) -> None:
    scheduler = StubScheduler([[]])
    storage = StubPersistence()

    dispatcher = Dispatcher(
        scheduler,
        {},
        persistence_module=storage,
    )

    job = make_job(99, "sync", attempts=2)
    start = time.perf_counter()

    await dispatcher._handle_failure(
        job,
        RuntimeError("lease lost"),
        start,
        lease_lost=True,
    )

    assert storage.fail_calls == []
    assert storage.dlq_calls == []

    heartbeat_events = [
        payload for event_name, payload in captured_events if event_name == "orchestrator.heartbeat"
    ]
    assert heartbeat_events
    assert heartbeat_events[-1]["status"] == "skip_failure"


@pytest.mark.asyncio
async def test_default_handlers_bind_sync_job(tmp_path: Path) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    class InlineSoulseekClient:
        def __init__(self) -> None:
            self.calls: list[Mapping[str, Any]] = []

        async def download(self, payload: Mapping[str, Any]) -> None:
            self.calls.append(dict(payload))

    soulseek = InlineSoulseekClient()
    deps = SyncHandlerDeps(
        soulseek_client=soulseek,
        retry_policy_override=SyncRetryPolicy(max_attempts=3, base_seconds=1.0, jitter_pct=0.0),
        rng=random.Random(0),
        music_dir=tmp_path,
    )
    handlers = default_handlers(deps)
    assert "sync" in handlers

    with session_scope() as session:
        record = Download(
            filename="handler.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=1,
        )
        session.add(record)
        session.flush()
        download_id = record.id

    job = make_job(
        99,
        "sync",
        attempts=1,
        payload={
            "username": "tester",
            "files": [{"download_id": download_id, "priority": 1, "filename": "handler.mp3"}],
        },
    )

    result = await handlers["sync"](job)
    assert result == {"username": "tester", "download_ids": [download_id]}
    assert soulseek.calls

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "downloading"


@pytest.mark.asyncio
async def test_default_handlers_bind_matching_job(tmp_path: Path) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    class InlineSoulseekClient:
        async def download(self, payload: Mapping[str, Any]) -> None:  # pragma: no cover - unused
            return None

    soulseek = InlineSoulseekClient()
    deps = SyncHandlerDeps(
        soulseek_client=soulseek,  # type: ignore[arg-type]
        retry_policy_override=SyncRetryPolicy(max_attempts=3, base_seconds=1.0, jitter_pct=0.0),
        rng=random.Random(0),
        music_dir=tmp_path,
    )
    matching_deps = MatchingHandlerDeps(
        engine=MusicMatchingEngine(),
        session_factory=session_scope,
        confidence_threshold=0.3,
    )
    handlers = default_handlers(deps, matching_deps=matching_deps)

    assert "matching" in handlers

    payload = {
        "type": "spotify-to-soulseek",
        "spotify_track": {
            "id": "track-1",
            "name": "Sample Song",
            "artists": [{"name": "Sample Artist"}],
        },
        "candidates": [
            {"id": "cand-1", "filename": "Sample Song.mp3", "username": "dj", "bitrate": 320},
            {"id": "cand-2", "filename": "Other.mp3", "username": "other", "bitrate": 128},
        ],
    }

    job = make_job(100, "matching", attempts=1, payload=payload)
    result = await handlers["matching"](job)

    assert result["stored"] == 1
    assert result["discarded"] == 1

    with session_scope() as session:
        matches = session.execute(select(Match)).scalars().all()
        assert len(matches) == 1
        assert matches[0].target_id == "cand-1"
