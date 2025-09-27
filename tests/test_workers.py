import pytest
from sqlalchemy import select

from app.core.matching_engine import MusicMatchingEngine
from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Match, WorkerJob
from app.utils.settings_store import read_setting
from app.workers.matching_worker import MatchingWorker
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

    await worker.enqueue({"username": "tester", "files": [{"id": 1, "download_id": 1}]})

    assert client.downloads, "Download should be triggered even when worker is stopped"

    with session_scope() as session:
        job = session.execute(select(WorkerJob)).scalar_one()
        assert job.state == "completed"
        assert job.attempts == 1

    assert read_setting("metrics.sync.jobs_completed") == "1"


@pytest.mark.asyncio
async def test_matching_worker_batch_processing() -> None:
    reset_engine_for_tests()
    init_db()
    engine = MusicMatchingEngine()
    worker = MatchingWorker(engine, batch_size=2, confidence_threshold=0.3)

    job_payload = {
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

    await worker.enqueue(job_payload)

    with session_scope() as session:
        matches = session.execute(select(Match)).scalars().all()
        assert len(matches) == 1
        assert matches[0].target_id == "cand-1"

    assert read_setting("metrics.matching.last_discarded") == "1"
