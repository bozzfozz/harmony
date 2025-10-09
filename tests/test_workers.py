import pytest
from sqlalchemy import select

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download, QueueJob, QueueJobStatus
from app.utils.settings_store import read_setting
from app.workers.sync_worker import SyncWorker


class DummySoulseekClient:
    def __init__(self) -> None:
        self.downloads: list[dict] = []

    async def download(self, payload: dict) -> None:
        self.downloads.append(payload)

    async def get_download_status(self) -> list[dict]:
        return []


@pytest.mark.asyncio
async def test_sync_worker_persists_jobs() -> None:
    reset_engine_for_tests()
    init_db()
    client = DummySoulseekClient()
    worker = SyncWorker(client, concurrency=1)

    with session_scope() as session:
        download = Download(
            filename="handler.mp3",
            state="queued",
            progress=0.0,
            priority=1,
            username="tester",
        )
        session.add(download)
        session.flush()
        download_id = download.id

    await worker.enqueue(
        {
            "username": "tester",
            "files": [{"id": download_id, "download_id": download_id}],
        }
    )

    assert client.downloads, "Download should be triggered even when worker is stopped"

    with session_scope() as session:
        job = session.execute(select(QueueJob)).scalar_one()
        assert job.status == QueueJobStatus.COMPLETED.value
        assert job.attempts == 1

    assert read_setting("metrics.sync.jobs_completed") == "1"
