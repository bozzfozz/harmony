"""Focused tests for single item submission handling in the Harmony Download Manager."""

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
    DownloadWorkItem,
)
from app.hdm.orchestrator import HdmOrchestrator
from app.hdm.pipeline import DownloadPipeline
from tests.orchestrator._flow_fixtures import (  # noqa: F401
    configure_environment,
    reset_activity_manager,
)


class _ImmediatePipeline(DownloadPipeline):
    """Pipeline stub returning deterministic outcomes for assertions."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, work_item: DownloadWorkItem) -> DownloadOutcome:  # type: ignore[override]
        self.calls.append(work_item.item.item_id)
        work_item.record_event(
            "pipeline.accepted",
            meta={"attempt": work_item.attempt},
            timestamp=datetime.now(timezone.utc),
        )
        await asyncio.sleep(0)
        return DownloadOutcome(
            final_path=Path("/library") / f"{work_item.item.item_id}.flac",
            tags_written=True,
            bytes_written=4096,
            track_duration_seconds=245.0,
            quality="FLAC",
            events=(),
        )


@pytest.mark.asyncio
async def test_submit_single_returns_success_summary() -> None:
    pipeline = _ImmediatePipeline()
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=2,
        max_retries=3,
        batch_max_items=25,
    )

    handle = await orchestrator.submit_single(
        DownloadRequestItem(
            artist="The Artists",
            title="Track One",
            album="Album",
            isrc="ABCD12345678",
            requested_by="tester",
        )
    )

    summary = await handle.wait()

    assert summary.status is BatchStatus.SUCCESS
    assert summary.totals.succeeded == 1
    assert summary.items[0].final_path == Path("/library") / f"{summary.items[0].item_id}.flac"
    assert pipeline.calls and pipeline.calls[0] == summary.items[0].item_id

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_submit_single_requires_requested_by() -> None:
    pipeline = _ImmediatePipeline()
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=1,
        max_retries=1,
        batch_max_items=5,
    )

    with pytest.raises(ValueError):
        await orchestrator.submit_single(
            DownloadRequestItem(artist="Artist", title="Track", requested_by=""),
        )

    await orchestrator.shutdown()


@pytest.mark.asyncio
async def test_batch_request_normalises_requested_by() -> None:
    pipeline = _ImmediatePipeline()
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=InMemoryIdempotencyStore(),
        worker_concurrency=1,
        max_retries=2,
        batch_max_items=10,
    )

    request = DownloadBatchRequest(
        items=[
            DownloadRequestItem(artist="Artist", title="Track", requested_by="  "),
        ],
        requested_by="BatchUser",
    )

    handle = await orchestrator.submit_batch(request)
    summary = await handle.wait()

    assert summary.requested_by == "BatchUser"
    assert summary.items[0].tags_written is True

    await orchestrator.shutdown()
