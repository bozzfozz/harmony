"""Concurrency tests for queue persistence enqueue behaviour."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any
import anyio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import QueueJob
from app.workers import persistence
from app.workers.persistence import enqueue


@pytest.mark.anyio
async def test_enqueue_is_atomic_under_concurrency() -> None:
    payload_template = {"idempotency_key": "concurrent-job"}
    results: list[int] = []

    async def call(index: int) -> None:
        payload = dict(payload_template)
        payload["payload"] = {"value": index}
        job = await anyio.to_thread.run_sync(enqueue, "matching", payload)
        results.append(job.id)

    async with anyio.create_task_group() as tg:
        for idx in range(8):
            tg.start_soon(call, idx)

    assert len(results) == 8
    assert len(set(results)) == 1

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == "matching")
        count = session.execute(stmt).scalar_one()
        assert count == 1

        record_stmt = select(QueueJob).where(QueueJob.type == "matching")
        record = session.execute(record_stmt).scalars().one()
        assert record.status == "pending"
        # The final payload should correspond to one of the attempted updates.
        assert record.payload["payload"]["value"] in range(8)


@pytest.mark.anyio
async def test_enqueue_returns_single_job_for_conflicting_requests() -> None:
    """Ensure the DTO returned from concurrent enqueues references the same record."""

    payload = {"idempotency_key": "conflict", "payload": {"value": 1}}
    ids: list[int] = []

    async def run() -> None:
        job = await anyio.to_thread.run_sync(enqueue, "metadata", payload)
        ids.append(job.id)

    async with anyio.create_task_group() as tg:
        for _ in range(2):
            tg.start_soon(run)

    assert len(ids) == 2
    assert len(set(ids)) == 1

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


@pytest.fixture(params=["sqlite", "postgresql"], ids=["sqlite", "postgresql"])
def queue_database_backend(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
):
    original_url = os.environ["DATABASE_URL"]
    backend = request.param
    schema_name: str | None = None
    base_engine: sa.Engine | None = None
    configured_url: str | None = None

    try:
        if backend == "sqlite":
            db_path = tmp_path_factory.mktemp("queue-db") / f"{uuid.uuid4().hex}.db"
            configured_url = f"sqlite:///{db_path}"
            monkeypatch.setenv("DATABASE_URL", configured_url)
            reset_engine_for_tests()
            init_db()
            yield backend
        else:
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
            yield backend
    finally:
        reset_engine_for_tests()
        monkeypatch.setenv("DATABASE_URL", original_url)

        if backend == "sqlite" and configured_url is not None:
            sqlite_url = make_url(configured_url)
            database = sqlite_url.database or ""
            if database:
                db_path = Path(database)
                for suffix in ("", "-journal", "-wal", "-shm"):
                    candidate = db_path.with_name(f"{db_path.name}{suffix}")
                    if candidate.exists():
                        candidate.unlink()

        if backend == "postgresql" and base_engine is not None and schema_name is not None:
            with base_engine.connect() as connection:
                try:
                    connection.execute(DropSchema(schema_name, cascade=True))
                    connection.commit()
                except ProgrammingError:
                    connection.rollback()
            base_engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("queue_database_backend", ["sqlite", "postgresql"], indirect=True)
async def test_enqueue_conflict_returns_existing_job_on_integrity_error(
    queue_database_backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_type = f"conflict-{queue_database_backend}"
    template = {"idempotency_key": f"{job_type}-job"}
    concurrency = 8
    barrier = threading.Barrier(concurrency)

    dedupe_events: list[dict[str, Any]] = []
    lock = threading.Lock()
    original_debug = persistence.logger.debug

    def capture_debug(message: str, *args: Any, **kwargs: Any) -> None:
        extra = kwargs.get("extra")
        if isinstance(extra, dict) and extra.get("event") == "queue.job.dedupe":
            with lock:
                dedupe_events.append({"message": message, "extra": extra})
        original_debug(message, *args, **kwargs)

    monkeypatch.setattr(persistence.logger, "debug", capture_debug)

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

    with session_scope() as session:
        stmt = select(func.count()).select_from(QueueJob).where(QueueJob.type == job_type)
        count = session.execute(stmt).scalar_one()
        assert count == 1

        record_stmt = select(QueueJob).where(QueueJob.type == job_type)
        record = session.execute(record_stmt).scalars().one()
        payload_data = record.payload.get("payload") if isinstance(record.payload, dict) else None
        assert isinstance(payload_data, dict)
        assert payload_data.get("attempt") in range(concurrency + 1)
