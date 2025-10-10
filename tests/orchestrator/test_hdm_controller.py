from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.hdm.idempotency import InMemoryIdempotencyStore
from app.hdm.models import (
    BatchStatus,
    DownloadBatchRequest,
    DownloadOutcome,
    DownloadRequestItem,
    ItemEvent,
    ItemState,
    DownloadWorkItem,
)
from app.hdm.orchestrator import HdmOrchestrator
from app.hdm.pipeline import DownloadPipeline, RetryableDownloadError


class RecordingPipeline(DownloadPipeline):
    def __init__(self) -> None:
        self.order: list[tuple[str, str]] = []

    async def execute(self, work_item: DownloadWorkItem) -> DownloadOutcome:  # type: ignore[override]
        self.order.append((work_item.item.batch_id, work_item.item.item_id))
        work_item.record_event(
            "download.accepted",
            meta={"attempt": work_item.attempt},
            timestamp=datetime.now(timezone.utc),
        )
        await asyncio.sleep(0)
        return DownloadOutcome(
            final_path=Path(f"/data/music/{work_item.item.item_id}.flac"),
            tags_written=True,
            bytes_written=1024,
            track_duration_seconds=180.0,
            quality="FLAC",
            events=(
                ItemEvent(
                    name="metadata.enriched",
                    timestamp=datetime.now(timezone.utc),
                    meta={"source": "spotify"},
                ),
                ItemEvent(
                    name="file.moved",
                    timestamp=datetime.now(timezone.utc),
                    meta={"target": "library"},
                ),
            ),
        )


@pytest.mark.asyncio
async def test_single_and_batch_flow_share_pipeline() -> None:
    pipeline = RecordingPipeline()
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=2,
        max_retries=3,
        batch_max_items=10,
    )

    single_item = DownloadRequestItem(artist="Artist", title="Track", requested_by="tester")
    single_handle = await orchestrator.submit_single(single_item)
    single_summary = await single_handle.wait()
    assert single_summary.totals.succeeded == 1
    assert single_summary.status is BatchStatus.SUCCESS

    batch_request = DownloadBatchRequest(
        items=[
            DownloadRequestItem(artist="A", title="One", requested_by="tester"),
            DownloadRequestItem(artist="B", title="Two"),
        ],
        requested_by="tester",
    )
    batch_handle = await orchestrator.submit_batch(batch_request)
    batch_summary = await batch_handle.wait()
    assert batch_summary.totals.succeeded == 2
    assert batch_summary.status is BatchStatus.SUCCESS
    assert len(pipeline.order) == 3

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_batches_processed_round_robin() -> None:
    pipeline = RecordingPipeline()
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=1,
        max_retries=2,
        batch_max_items=10,
    )
    batch_one = DownloadBatchRequest(
        items=[
            DownloadRequestItem(artist="X", title="One", requested_by="tester"),
            DownloadRequestItem(artist="X", title="Two"),
        ],
        requested_by="tester",
    )
    batch_two = DownloadBatchRequest(
        items=[
            DownloadRequestItem(artist="Y", title="Three", requested_by="tester"),
            DownloadRequestItem(artist="Y", title="Four"),
        ],
        requested_by="tester",
    )

    handle_one = await orchestrator.submit_batch(batch_one)
    handle_two = await orchestrator.submit_batch(batch_two)
    await asyncio.gather(handle_one.wait(), handle_two.wait())

    order = [batch_id for batch_id, _ in pipeline.order]
    assert order[:4] == [order[0], order[1], order[0], order[1]]
    await orchestrator.shutdown()


class FlakyPipeline(DownloadPipeline):
    def __init__(self, retries_before_success: int) -> None:
        self.retries_before_success = retries_before_success
        self.invocations = 0

    async def execute(self, work_item: DownloadWorkItem) -> DownloadOutcome:  # type: ignore[override]
        self.invocations += 1
        if self.invocations <= self.retries_before_success:
            raise RetryableDownloadError("temporary failure", retry_after_seconds=0.01)
        return DownloadOutcome(
            final_path=Path("/data/music/success.flac"),
            tags_written=True,
            bytes_written=2048,
            track_duration_seconds=200.0,
            quality="FLAC",
            events=(),
        )


@pytest.mark.asyncio
async def test_retry_until_success() -> None:
    pipeline = FlakyPipeline(retries_before_success=1)
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=1,
        max_retries=3,
        batch_max_items=5,
        retry_base_seconds=0.0,
    )
    request = DownloadBatchRequest(
        items=[DownloadRequestItem(artist="Retry", title="Song", requested_by="tester")],
        requested_by="tester",
    )
    summary = await (await orchestrator.submit_batch(request)).wait()
    assert summary.totals.retries == 1
    item = summary.items[0]
    assert item.attempts == 2
    assert item.error is None
    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_duplicate_items_skipped_after_success() -> None:
    pipeline = RecordingPipeline()
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=1,
        max_retries=2,
        batch_max_items=5,
    )
    duplicate_request = DownloadBatchRequest(
        items=[
            DownloadRequestItem(artist="Dup", title="Song", requested_by="tester"),
            DownloadRequestItem(artist="Dup", title="Song"),
        ],
        requested_by="tester",
    )
    summary = await (await orchestrator.submit_batch(duplicate_request)).wait()
    assert summary.totals.duplicates == 1
    assert summary.totals.dedupe_hits == 1
    states = {result.state for result in summary.items}
    assert states == {ItemState.DONE, ItemState.DUPLICATE}
    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_percentile_statistics(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = RecordingPipeline()
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=1,
        max_retries=2,
        batch_max_items=5,
    )
    monotonic_values = iter([0.0, 1.0, 1.0, 2.2, 2.2, 3.4])

    def fake_monotonic() -> float:
        return next(monotonic_values)

    monkeypatch.setattr("app.hdm.orchestrator.time.monotonic", fake_monotonic)

    request = DownloadBatchRequest(
        items=[
            DownloadRequestItem(artist="Timing", title="One", requested_by="tester"),
            DownloadRequestItem(artist="Timing", title="Two"),
            DownloadRequestItem(artist="Timing", title="Three"),
        ],
        requested_by="tester",
    )
    summary = await (await orchestrator.submit_batch(request)).wait()
    assert pytest.approx(summary.durations.p95_seconds, rel=0.05) == 1.2
    assert pytest.approx(summary.durations.p99_seconds, rel=0.05) == 1.2
    await orchestrator.shutdown()
