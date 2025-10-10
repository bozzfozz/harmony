from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import override_runtime_env
from app.orchestrator.download_flow import aggregation as aggregation_module
from app.orchestrator.download_flow.models import (
    DownloadItem,
    DownloadOutcome,
    ItemEvent,
)
from app.utils import metrics


@pytest.fixture(autouse=True)
def configure_environment(monkeypatch: pytest.MonkeyPatch) -> None:  # pragma: no cover - override global autouse
    """Override the repository-level configure_environment fixture."""

    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    override_runtime_env(None)
    yield


@pytest.fixture(autouse=True)
def reset_activity_manager() -> None:  # pragma: no cover - override global autouse
    """Disable the global activity manager reset that requires the database."""

    yield


def _collect_metric_samples() -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    registry = metrics.get_registry()
    samples: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
    for metric in registry.collect():
        for sample in metric.samples:
            labels = tuple(sorted(sample.labels.items()))
            samples[(sample.name, labels)] = sample.value
    return samples


def _make_item(batch_id: str = "batch-1") -> DownloadItem:
    return DownloadItem(
        batch_id=batch_id,
        item_id="item-1",
        artist="Artist",
        title="Title",
        album=None,
        isrc=None,
        requested_by="tester",
        priority=1,
        dedupe_key="artist-title",
    )


@pytest.mark.asyncio()
async def test_record_success_emits_phase_metrics() -> None:
    metrics.reset_registry()
    aggregation_module.register_metrics()
    aggregator = aggregation_module.DownloadBatchAggregator()
    state = aggregator.create_batch("batch-1", requested_by="tester", total=1)
    item = _make_item()

    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    events = [
        ItemEvent(name="download.accepted", timestamp=base, meta=None),
        ItemEvent(
            name="download.detected",
            timestamp=base + timedelta(seconds=1),
            meta=None,
        ),
        ItemEvent(
            name="tagging.completed",
            timestamp=base + timedelta(seconds=2),
            meta=None,
        ),
        ItemEvent(
            name="file.moved",
            timestamp=base + timedelta(seconds=3),
            meta=None,
        ),
    ]

    outcome = DownloadOutcome(
        final_path=Path("/tmp/final.mp3"),
        tags_written=True,
        bytes_written=123,
        track_duration_seconds=200.0,
        quality="mp3/320",
        events=(),
    )

    await aggregator.record_success(
        state,
        item,
        outcome=outcome,
        attempts=1,
        processing_seconds=3.5,
        events=events,
    )

    samples = _collect_metric_samples()
    assert samples[("download_flow_item_outcomes_total", (("state", "done"),))] == 1.0
    assert samples[("download_flow_processing_seconds_count", ())] == 1.0
    assert samples[("download_flow_processing_seconds_sum", ())] == pytest.approx(3.5)
    assert samples[
        (
            "download_flow_phase_duration_seconds_count",
            (("phase", "download"),),
        )
    ] == 1.0
    assert samples[
        (
            "download_flow_phase_duration_seconds_sum",
            (("phase", "download"),),
        )
    ] == pytest.approx(1.0)
    assert samples[
        (
            "download_flow_phase_duration_seconds_sum",
            (("phase", "tagging"),),
        )
    ] == pytest.approx(1.0)
    assert samples[
        (
            "download_flow_phase_duration_seconds_sum",
            (("phase", "moving"),),
        )
    ] == pytest.approx(1.0)


@pytest.mark.asyncio()
async def test_record_failure_tracks_failure_metrics() -> None:
    metrics.reset_registry()
    aggregation_module.register_metrics()
    aggregator = aggregation_module.DownloadBatchAggregator()
    state = aggregator.create_batch("batch-1", requested_by="tester", total=1)
    item = _make_item()

    await aggregator.record_failure(
        state,
        item,
        attempts=2,
        error=ValueError("boom"),
        processing_seconds=4.2,
    )

    samples = _collect_metric_samples()
    assert samples[("download_flow_item_outcomes_total", (("state", "failed"),))] == 1.0
    assert samples[
        ("download_flow_item_failures_total", (("error_type", "ValueError"),))
    ] == 1.0
    assert samples[("download_flow_processing_seconds_count", ())] == 1.0
    assert samples[("download_flow_processing_seconds_sum", ())] == pytest.approx(4.2)


@pytest.mark.asyncio()
async def test_record_retry_and_duplicate_metrics() -> None:
    metrics.reset_registry()
    aggregation_module.register_metrics()
    aggregator = aggregation_module.DownloadBatchAggregator()
    state = aggregator.create_batch("batch-1", requested_by="tester", total=1)
    item = _make_item()

    await aggregator.record_retry(
        state,
        item,
        attempt=1,
        error=RuntimeError("transient"),
        retry_after=1.5,
    )

    await aggregator.record_duplicate(
        state,
        item,
        reason="duplicate",
        already_processed=True,
    )

    samples = _collect_metric_samples()
    assert samples[
        ("download_flow_item_retries_total", (("error_type", "RuntimeError"),))
    ] == 1.0
    assert samples[("download_flow_duplicates_total", (("already_processed", "true"),))] == 1.0
    assert samples[("download_flow_dedupe_hits_total", ())] == 1.0
    assert samples[("download_flow_item_outcomes_total", (("state", "duplicate"),))] == 1.0
