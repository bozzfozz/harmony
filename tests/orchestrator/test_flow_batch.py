"""Stress tests for batch processing behaviour of the download flow orchestrator."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.orchestrator.download_flow.controller import DownloadFlowOrchestrator
from app.orchestrator.download_flow.idempotency import InMemoryIdempotencyStore
from app.orchestrator.download_flow.models import (
    BatchStatus,
    DownloadBatchRequest,
    DownloadOutcome,
    DownloadRequestItem,
    DownloadWorkItem,
    ItemState,
)
from app.orchestrator.download_flow.pipeline import DownloadPipeline
from tests.orchestrator._flow_fixtures import (  # noqa: F401
    configure_environment,
    reset_activity_manager,
)


class _ConcurrentTrackingPipeline(DownloadPipeline):
    """Pipeline recording peak concurrency and processed item identifiers."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._running = 0
        self.max_running = 0
        self.processed: list[str] = []

    async def execute(self, work_item: DownloadWorkItem) -> DownloadOutcome:  # type: ignore[override]
        async with self._lock:
            self._running += 1
            self.max_running = max(self.max_running, self._running)
        await asyncio.sleep(0)
        self.processed.append(work_item.item.item_id)
        async with self._lock:
            self._running -= 1
        return DownloadOutcome(
            final_path=Path("/library") / f"{work_item.item.item_id}.flac",
            tags_written=True,
            bytes_written=1024,
            track_duration_seconds=180.0,
            quality="FLAC",
            events=(),
        )


class _BlockingPipeline(DownloadPipeline):
    """Pipeline that blocks until explicitly released to test idempotency."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self._release = asyncio.Event()
        self.invocations: list[str] = []

    async def execute(self, work_item: DownloadWorkItem) -> DownloadOutcome:  # type: ignore[override]
        self.invocations.append(work_item.item.item_id)
        self.started.set()
        await self._release.wait()
        return DownloadOutcome(
            final_path=Path("/library") / f"{work_item.item.item_id}.flac",
            tags_written=True,
            bytes_written=2048,
            track_duration_seconds=200.0,
            quality="FLAC",
            events=(),
        )

    def release(self) -> None:
        self._release.set()


@pytest.mark.asyncio
async def test_high_volume_batch_respects_concurrency_limits() -> None:
    total_items = 1200
    pipeline = _ConcurrentTrackingPipeline()
    orchestrator = DownloadFlowOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=5,
        max_retries=2,
        batch_max_items=2000,
    )

    request = DownloadBatchRequest(
        items=[
            DownloadRequestItem(
                artist=f"Artist {index}",
                title=f"Song {index}",
                requested_by="stress",
            )
            for index in range(total_items)
        ],
        requested_by="stress",
    )

    handle = await orchestrator.submit_batch(request)
    summary = await handle.wait()

    assert summary.status is BatchStatus.SUCCESS
    assert summary.totals.total_items == total_items
    assert summary.totals.succeeded == total_items
    assert pipeline.max_running <= 5
    assert len(pipeline.processed) == total_items

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_idempotency_skips_in_progress_duplicates() -> None:
    pipeline = _BlockingPipeline()
    orchestrator = DownloadFlowOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=2,
        max_retries=1,
        batch_max_items=10,
    )

    dedupe_key = "duplicate-key"
    first_request = DownloadBatchRequest(
        items=[
            DownloadRequestItem(
                artist="Alpha",
                title="Song",
                dedupe_key=dedupe_key,
                requested_by="tester",
            ),
        ],
        requested_by="tester",
    )

    second_request = DownloadBatchRequest(
        items=[
            DownloadRequestItem(
                artist="Alpha",
                title="Song",
                dedupe_key=dedupe_key,
                requested_by="tester",
            )
        ],
        requested_by="tester",
    )

    first_handle = await orchestrator.submit_batch(first_request)
    await pipeline.started.wait()

    second_handle = await orchestrator.submit_batch(second_request)

    pipeline.release()

    first_summary, second_summary = await asyncio.gather(
        first_handle.wait(), second_handle.wait()
    )

    assert len(pipeline.invocations) == 1
    assert first_summary.totals.succeeded == 1
    assert second_summary.totals.duplicates == 1
    assert second_summary.items[0].state is ItemState.DUPLICATE
    assert "in_progress" in (second_summary.items[0].error or "")

    await orchestrator.shutdown()
