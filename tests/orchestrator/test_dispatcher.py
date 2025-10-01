from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

import pytest

from app.models import QueueJobStatus
from app.orchestrator import dispatcher as dispatcher_module
from app.orchestrator.dispatcher import Dispatcher
from app.workers import persistence


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


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Mapping[str, Any]]]:
    events: list[tuple[str, Mapping[str, Any]]] = []

    def recorder(logger: Any, event: str, /, **fields: Any) -> None:  # noqa: ANN401 - test helper
        events.append((event, dict(fields)))

    monkeypatch.setattr(dispatcher_module, "log_event", recorder)
    return events


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

    assert captured_events
    event_name, payload = captured_events[-1]
    assert event_name == "orchestrator.commit"
    assert payload["job_type"] == "sync"
    assert payload["job_id"] == 1
    assert payload["status"] == "succeeded"
    assert payload["attempts"] == 1


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

    assert captured_events
    event_name, payload = captured_events[-1]
    assert event_name == "orchestrator.commit"
    assert payload["status"] == "retry"
    assert payload["retry_in"] == 1


@pytest.mark.asyncio
async def test_dispatcher_moves_job_to_dlq_when_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    captured_events: list[tuple[str, Mapping[str, Any]]],
) -> None:
    caplog.set_level("INFO", logger="app.orchestrator.dispatcher")
    monkeypatch.setenv("EXTERNAL_RETRY_MAX", "2")
    monkeypatch.setenv("EXTERNAL_BACKOFF_BASE_MS", "100")
    monkeypatch.setenv("EXTERNAL_JITTER_PCT", "0")

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

    dispatcher = Dispatcher(scheduler, {"sync": handler}, persistence_module=storage)

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

    assert captured_events
    event_name, payload = captured_events[-1]
    assert event_name == "orchestrator.dlq"
    assert payload["stop_reason"] == "max_retries_exhausted"
