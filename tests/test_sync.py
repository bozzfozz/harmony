"""Tests for synchronisation job persistence and worker integration."""

from __future__ import annotations

import asyncio

import pytest

from app.db import SessionLocal, init_db
from backend.app.models.sync_job import SyncJob
from backend.app.workers.sync_worker import SyncWorker


@pytest.fixture(autouse=True)
def setup_database() -> None:
    """Ensure the sync_jobs table exists and is empty for each test."""

    init_db()
    with SessionLocal() as session:
        session.query(SyncJob).delete()
        session.commit()
    yield
    with SessionLocal() as session:
        session.query(SyncJob).delete()
        session.commit()


def _run(coro):
    """Helper to execute async code within sync tests."""

    return asyncio.run(coro)


def test_sync_job_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting a sync creates a pending job entry."""

    async def fake_sync_track(self, spotify_track_id: str) -> dict[str, str]:
        return {"id": spotify_track_id}

    monkeypatch.setattr(SyncWorker, "sync_track", fake_sync_track)

    worker = SyncWorker()

    async def scenario() -> None:
        job_id = await worker.start_sync("track-123")
        with SessionLocal() as session:
            job = session.get(SyncJob, job_id)
            assert job is not None
            assert job.spotify_id == "track-123"
            assert job.status == "pending"
        task = worker._tasks.get(job_id)
        if task is not None:
            await task

    _run(scenario())


def test_worker_updates_status_to_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful worker run marks the job as completed."""

    async def fake_sync_track(self, spotify_track_id: str) -> dict[str, str]:
        await asyncio.sleep(0)
        return {"id": spotify_track_id}

    monkeypatch.setattr(SyncWorker, "sync_track", fake_sync_track)

    worker = SyncWorker()

    async def scenario() -> None:
        job_id = await worker.start_sync("track-456")
        task = worker._tasks.get(job_id)
        if task is not None:
            await task
        with SessionLocal() as session:
            job = session.get(SyncJob, job_id)
            assert job is not None
            assert job.status == "completed"
            assert job.error_message is None

    _run(scenario())


def test_worker_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Errors during sync are persisted on the job record."""

    async def failing_sync_track(self, spotify_track_id: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(SyncWorker, "sync_track", failing_sync_track)

    worker = SyncWorker()

    async def scenario() -> None:
        job_id = await worker.start_sync("track-789")
        task = worker._tasks.get(job_id)
        if task is not None:
            await task
        with SessionLocal() as session:
            job = session.get(SyncJob, job_id)
            assert job is not None
            assert job.status == "failed"
            assert job.error_message == "boom"

    _run(scenario())
