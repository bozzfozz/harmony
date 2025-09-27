from __future__ import annotations

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download
from app.utils.settings_store import write_setting

try:
    from app.workers.scan_worker import ScanWorker
except ModuleNotFoundError:  # pragma: no cover - archived integration
    pytest.skip("Plex scan worker archived in MVP", allow_module_level=True)

from app.workers.sync_worker import SyncWorker
from tests.conftest import StubPlexClient, StubSoulseekClient


class StubScanWorker:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    async def request_scan(self, section_id: str | None = None) -> bool:
        self.calls.append(section_id)
        return True


@pytest.mark.asyncio
async def test_request_scan_dedupes() -> None:
    plex = StubPlexClient()
    worker = ScanWorker(plex)

    first = await worker.request_scan("1")
    second = await worker.request_scan("1")

    assert first is True
    assert second is False
    assert plex.refresh_calls == [("1", False)]


@pytest.mark.asyncio
async def test_sync_worker_triggers_scan_on_completion(tmp_path) -> None:
    reset_engine_for_tests()
    init_db()
    write_setting("MUSIC_DIR", str(tmp_path))

    with session_scope() as session:
        download = Download(filename="test.mp3", state="completed")
        session.add(download)
        session.commit()
        download_id = download.id

    scan_stub = StubScanWorker()
    sync_worker = SyncWorker(
        StubSoulseekClient(),
        metadata_worker=None,
        artwork_worker=None,
        lyrics_worker=None,
        scan_worker=scan_stub,
    )

    payload = {"state": "completed", "filename": "test.mp3"}
    await sync_worker._handle_download_completion(download_id, payload)

    assert scan_stub.calls == [None]
