import asyncio
from typing import Any

import pytest

from app.errors import DependencyError, NotFoundError
from app.models import Download
from app.schemas import DownloadPriorityUpdate, SoulseekDownloadRequest
from app.services.download_service import DownloadService


class StubTransfersApi:
    def __init__(self) -> None:
        self.cancelled: list[int] = []
        self.enqueued: list[tuple[str, list[dict[str, Any]]]] = []

    async def cancel_download(self, download_id: int) -> None:
        self.cancelled.append(download_id)

    async def enqueue(self, *, username: str, files: list[dict[str, Any]]) -> None:
        self.enqueued.append((username, files))


class StubWorker:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def enqueue(self, job: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        self.jobs.append(job)


def _service(db_session, transfers: StubTransfersApi | None = None) -> DownloadService:
    async def runner(func):
        return func(db_session)

    return DownloadService(
        session=db_session,
        session_runner=runner,
        transfers=transfers or StubTransfersApi(),
    )


def test_list_downloads_filters_active_states(db_session) -> None:
    active = Download(filename="queued.mp3", state="queued", progress=0.0, priority=10)
    done = Download(filename="done.mp3", state="completed", progress=1.0, priority=5)
    db_session.add_all([active, done])
    db_session.commit()

    service = _service(db_session)

    downloads = service.list_downloads(include_all=False, status_filter=None, limit=10, offset=0)
    assert [item.id for item in downloads] == [active.id]


def test_get_download_missing_raises(db_session) -> None:
    service = _service(db_session)

    with pytest.raises(NotFoundError):
        service.get_download(999)


def test_update_priority_persists_and_notifies_worker(monkeypatch, db_session) -> None:
    download = Download(
        filename="song.mp3",
        state="queued",
        progress=0.0,
        priority=1,
        request_payload={"filename": "song.mp3", "priority": 1},
    )
    db_session.add(download)
    db_session.commit()

    notified: dict[str, Any] = {}

    def fake_update_priority(job_id: int, priority: int, *, job_type: str) -> bool:
        notified.update({"job_id": job_id, "priority": priority, "job_type": job_type})
        return True

    monkeypatch.setattr("app.services.download_service.update_worker_priority", fake_update_priority)

    download.job_id = 42
    db_session.commit()

    service = _service(db_session)
    updated = service.update_priority(download.id, DownloadPriorityUpdate(priority=5))

    assert updated.priority == 5
    assert updated.request_payload["priority"] == 5
    assert notified["priority"] == 5
    assert notified["job_type"] == "sync"
    assert notified["job_id"] == str(download.job_id)


@pytest.mark.asyncio
async def test_queue_downloads_persists_and_enqueues(db_session) -> None:
    worker = StubWorker()
    service = _service(db_session)

    payload = SoulseekDownloadRequest(
        username="tester",
        files=[{"filename": "track.mp3", "priority": 4}],
    )

    response = await service.queue_downloads(payload, worker=worker)

    assert response["status"] == "queued"
    assert worker.jobs and worker.jobs[0]["username"] == "tester"


@pytest.mark.asyncio
async def test_queue_downloads_without_worker_raises(db_session) -> None:
    service = _service(db_session)

    payload = SoulseekDownloadRequest(username="tester", files=[{"filename": "track.mp3"}])

    with pytest.raises(DependencyError):
        await service.queue_downloads(payload, worker=None)
