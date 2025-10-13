from pathlib import Path

import pytest

from app.hdm.idempotency import SQLiteIdempotencyStore
from app.hdm.models import DownloadBatchRequest, DownloadOutcome, DownloadRequestItem
from app.hdm.orchestrator import HdmOrchestrator


class StubPipeline:
    def __init__(self, output_path: Path) -> None:
        self.processed: list[str] = []
        self._output_path = output_path
        self._output_path.parent.mkdir(parents=True, exist_ok=True)

    async def execute(self, work_item) -> DownloadOutcome:  # type: ignore[override]
        self.processed.append(work_item.item.dedupe_key)
        return DownloadOutcome(
            final_path=self._output_path,
            tags_written=False,
            bytes_written=0,
            track_duration_seconds=None,
            quality=None,
        )


@pytest.mark.asyncio()
async def test_orchestrator_uses_sqlite_idempotency(tmp_path: Path) -> None:
    store_path = tmp_path / "state" / "idempotency.db"
    store = SQLiteIdempotencyStore(store_path)
    pipeline = StubPipeline(tmp_path / "music" / "track.flac")
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=store,
        worker_concurrency=1,
        max_retries=1,
        batch_max_items=10,
    )

    item = DownloadRequestItem(
        artist="Artist",
        title="Title",
        requested_by="tester",
        dedupe_key="shared-key",
    )
    batch = DownloadBatchRequest(items=[item], requested_by="tester")
    await orchestrator.start()
    try:
        handle = await orchestrator.submit_batch(batch)
        summary = await handle.wait()
        assert summary.totals.succeeded == 1
        assert pipeline.processed == ["shared-key"]

        duplicate_item = DownloadRequestItem(
            artist="Artist",
            title="Title",
            requested_by="tester",
            dedupe_key="shared-key",
        )
        duplicate_batch = DownloadBatchRequest(items=[duplicate_item], requested_by="tester")
        duplicate_handle = await orchestrator.submit_batch(duplicate_batch)
        duplicate_summary = await duplicate_handle.wait()
        assert duplicate_summary.totals.duplicates == 1
        assert pipeline.processed == ["shared-key"]
    finally:
        await orchestrator.shutdown()
