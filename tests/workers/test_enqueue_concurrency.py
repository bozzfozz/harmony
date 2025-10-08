"""Concurrency tests for queue persistence enqueue behaviour."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import QueueJob, QueueJobStatus
from app.workers import persistence
from app.workers.persistence import QueueJobDTO, enqueue

pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("queue_database_backend")]


@pytest.mark.anyio
async def test_enqueue_idempotent_concurrency_creates_single_row() -> None:
    payload_template = {"idempotency_key": "concurrent-job"}
    results: list[int] = []
    concurrency = 50

    async def call(index: int) -> None:
        payload = dict(payload_template)
        payload["payload"] = {"value": index}
        job = await anyio.to_thread.run_sync(enqueue, "matching", payload)
        results.append(job.id)

    async with anyio.create_task_group() as tg:
        for idx in range(concurrency):
            tg.start_soon(call, idx)

    assert len(results) == concurrency
    assert len(set(results)) == 1

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == "matching")
        count = session.execute(stmt).scalar_one()
        assert count == 1

        record_stmt = select(QueueJob).where(QueueJob.type == "matching")
        record = session.execute(record_stmt).scalars().one()
        assert record.status == "pending"
        # The final payload should correspond to one of the attempted updates.
        assert record.payload["payload"]["value"] in range(concurrency)


@pytest.mark.anyio
async def test_enqueue_duplicate_returns_existing_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the DTO returned from concurrent enqueues references the same record."""

    payload = {"idempotency_key": "conflict", "payload": {"value": 1}}
    ids: list[int] = []
    events: list[dict[str, Any]] = []

    original_log_event = persistence.log_event

    def capture_event(logger: Any, event: str, /, **fields: Any) -> None:
        events.append({"event": event, **fields})
        original_log_event(logger, event, **fields)

    monkeypatch.setattr(persistence, "log_event", capture_event)

    async def run() -> None:
        job = await anyio.to_thread.run_sync(enqueue, "metadata", payload)
        ids.append(job.id)

    async with anyio.create_task_group() as tg:
        for _ in range(2):
            tg.start_soon(run)

    assert len(ids) == 2
    assert len(set(ids)) == 1

    enqueued_events = [
        event
        for event in events
        if event.get("event") == "worker.job" and event.get("status") == "enqueued"
    ]
    assert enqueued_events, "expected worker.job events to be emitted"
    dedup_flags = [event.get("meta", {}).get("dedup") for event in enqueued_events]
    assert True in dedup_flags
    assert False in dedup_flags

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == "metadata")
        count = session.execute(stmt).scalar_one()
        assert count == 1

        job_stmt = select(QueueJob.id).where(QueueJob.type == "metadata")
        job_id = session.execute(job_stmt).scalar_one()
        assert job_id is not None


@pytest.mark.anyio
async def test_enqueue_parallel_requests_return_existing_job() -> None:
    """Parallel enqueue calls should return the existing job without raising errors."""

    job_type = "parallel"
    template = {"idempotency_key": "parallel-job"}
    concurrency = 6
    barrier = threading.Barrier(concurrency)

    def run_parallel() -> list[int]:
        results: list[int] = []

        def worker(idx: int) -> int:
            payload = dict(template)
            payload["payload"] = {"attempt": idx}
            barrier.wait()
            job = enqueue(job_type, payload)
            return job.id

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            for job_id in executor.map(worker, range(concurrency)):
                results.append(job_id)

        return results

    results = await anyio.to_thread.run_sync(run_parallel)

    assert len(results) == concurrency
    assert len(set(results)) == 1

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == job_type)
        count = session.execute(stmt).scalar_one()
        assert count == 1

        record_stmt = select(QueueJob).where(QueueJob.type == job_type)
        record = session.execute(record_stmt).scalars().one()
        payload_data = record.payload.get("payload") if isinstance(record.payload, dict) else None
        assert isinstance(payload_data, dict)
        assert payload_data.get("attempt") in range(concurrency)


def test_enqueue_redelivery_does_not_duplicate_on_retry() -> None:
    job_type = "retryable"
    dedupe_key = "retryable-job"

    original = enqueue(job_type, {"idempotency_key": dedupe_key, "payload": {"stage": "initial"}})
    assert original.idempotency_key == dedupe_key

    leased = persistence.lease(original.id, job_type=job_type)
    assert leased is not None
    assert leased.id == original.id

    assert persistence.fail(original.id, job_type=job_type, retry_in=0)

    updated = enqueue(
        job_type,
        {"idempotency_key": dedupe_key, "payload": {"stage": "retry"}},
    )

    assert updated.id == original.id
    assert updated.payload["payload"]["stage"] == "retry"

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == job_type)
        count = session.execute(stmt).scalar_one()
        assert count == 1

        record = session.execute(select(QueueJob).where(QueueJob.id == original.id)).scalars().one()
        assert record.payload["payload"]["stage"] == "retry"


@pytest.fixture()
def queue_database_backend(
    monkeypatch: pytest.MonkeyPatch,
):
    original_url = os.environ["DATABASE_URL"]
    schema_name: str | None = None
    base_engine: sa.Engine | None = None
    configured_url: str | None = None

    try:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            pytest.skip("DATABASE_URL is not configured for PostgreSQL tests")

        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            pytest.skip("PostgreSQL URL required for worker persistence tests")

        schema_name = f"test_workers_{uuid.uuid4().hex}"
        base_engine = sa.create_engine(url)
        with base_engine.connect() as connection:
            connection.execute(CreateSchema(schema_name))
            connection.commit()

        scoped_url = url.set(query={**url.query, "options": f"-csearch_path={schema_name}"})
        configured_url = str(scoped_url)
        monkeypatch.setenv("DATABASE_URL", configured_url)
        reset_engine_for_tests()
        init_db()
        yield "postgresql"
    finally:
        reset_engine_for_tests()
        monkeypatch.setenv("DATABASE_URL", original_url)

        if base_engine is not None and schema_name is not None:
            with base_engine.connect() as connection:
                try:
                    connection.execute(DropSchema(schema_name, cascade=True))
                    connection.commit()
                except ProgrammingError:
                    connection.rollback()
            base_engine.dispose()


@pytest.mark.anyio
async def test_enqueue_conflict_returns_existing_job_on_integrity_error(
    queue_database_backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_type = f"conflict-{queue_database_backend}"
    template = {"idempotency_key": f"{job_type}-job"}
    concurrency = 8
    barrier = threading.Barrier(concurrency)

    dedupe_events: list[dict[str, Any]] = []
    emitted_events: list[dict[str, Any]] = []
    lock = threading.Lock()
    original_debug = persistence.logger.debug
    original_emit = persistence._emit_worker_job_event

    def capture_debug(message: str, *args: Any, **kwargs: Any) -> None:
        extra = kwargs.get("extra")
        if isinstance(extra, dict) and extra.get("event") == "queue.job.dedupe":
            with lock:
                dedupe_events.append({"message": message, "extra": extra})
        original_debug(message, *args, **kwargs)

    def capture_emit(job: QueueJobDTO, status: str, *, deduped=None, **kwargs: Any) -> None:
        with lock:
            emitted_events.append(
                {
                    "job_id": int(job.id),
                    "status": status,
                    "deduped": bool(deduped),
                    "extra": dict(kwargs),
                }
            )
        original_emit(job, status, deduped=deduped, **kwargs)

    monkeypatch.setattr(persistence.logger, "debug", capture_debug)
    monkeypatch.setattr(persistence, "_emit_worker_job_event", capture_emit)

    def run_parallel() -> list[int]:
        results: list[int] = []

        def worker(idx: int) -> int:
            payload = dict(template)
            payload["payload"] = {"attempt": idx}
            barrier.wait()
            job = enqueue(job_type, payload)
            return job.id

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            for job_id in executor.map(worker, range(concurrency)):
                results.append(job_id)

        return results

    results = await anyio.to_thread.run_sync(run_parallel)

    assert len(results) == concurrency
    assert len(set(results)) == 1

    existing_id = results[0]
    final_payload = dict(template)
    final_payload["payload"] = {"attempt": concurrency}
    final_job = await anyio.to_thread.run_sync(enqueue, job_type, final_payload)
    assert final_job.id == existing_id

    assert dedupe_events, "Expected a dedupe log entry for concurrent enqueue conflict"
    assert any(event["extra"].get("job_type") == job_type for event in dedupe_events)
    assert any(event["extra"].get("dialect") == queue_database_backend for event in dedupe_events)

    deduped_event_job_ids = {event["job_id"] for event in emitted_events if event["deduped"]}
    assert deduped_event_job_ids == {existing_id}

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == job_type)
        count = session.execute(stmt).scalar_one()
        assert count == 1

        record_stmt = select(QueueJob).where(QueueJob.type == job_type)
        record = session.execute(record_stmt).scalars().one()
        payload_data = record.payload.get("payload") if isinstance(record.payload, dict) else None
        assert isinstance(payload_data, dict)
        assert payload_data.get("attempt") in range(concurrency + 1)


def test_enqueue_resets_attempts_when_previous_job_completed() -> None:
    job_type = "integrity-dedupe"
    dedupe_key = f"{job_type}-job"

    initial = enqueue(
        job_type,
        {"idempotency_key": dedupe_key, "payload": {"sequence": "initial"}},
        priority=1,
    )

    with session_scope() as session:
        record = session.get(QueueJob, initial.id)
        assert record is not None
        record.status = QueueJobStatus.COMPLETED.value
        record.attempts = 4
        session.add(record)

    updated = enqueue(
        job_type,
        {"idempotency_key": dedupe_key, "payload": {"sequence": "updated"}},
        priority=7,
    )

    assert updated.id == initial.id
    assert updated.priority == 7
    assert updated.payload["payload"]["sequence"] == "updated"
    assert updated.attempts == 0
    assert updated.status == QueueJobStatus.PENDING

    with session_scope() as session:
        refreshed = session.get(QueueJob, updated.id)
        assert refreshed is not None
        assert refreshed.priority == 7
        assert refreshed.attempts == 0
        assert refreshed.status == QueueJobStatus.PENDING.value
        assert refreshed.payload["payload"]["sequence"] == "updated"


def test_lease_telemetry_hook_records_status_transitions() -> None:
    seen: list[tuple[str, int, int]] = []

    def hook(job: QueueJobDTO, status: str, meta: dict[str, Any]) -> None:
        seen.append((status, int(meta["lease_timeout"]), int(job.id)))

    persistence.register_lease_telemetry_hook(hook)
    try:
        job = enqueue(
            "telemetry",
            {"payload": {"value": "hook"}, "idempotency_key": "telemetry-hook"},
            priority=9,
        )

        leased = persistence.lease(job.id, job_type=job.type, lease_seconds=45)
        assert leased is not None
        assert persistence.heartbeat(job.id, job_type=job.type, lease_seconds=15)

        assert [entry[0] for entry in seen] == ["leased", "heartbeat"]
        assert seen[0][1] == 45
        assert seen[1][1] == 15
        assert all(entry[2] == job.id for entry in seen)
    finally:
        persistence.register_lease_telemetry_hook(None)
