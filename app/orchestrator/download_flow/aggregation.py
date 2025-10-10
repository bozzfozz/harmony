"""Aggregation helpers for download batch orchestration."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from app.logging import get_logger
from app.logging_events import log_event
from app.utils.metrics import counter, histogram

from .models import (
    BatchStatus,
    BatchSummary,
    BatchTotals,
    DownloadItem,
    DownloadItemResult,
    DownloadOutcome,
    DurationStats,
    ItemEvent,
    ItemState,
)

_logger = get_logger(__name__)


_ITEM_OUTCOME_COUNTER: Any
_RETRY_COUNTER: Any
_FAILURE_COUNTER: Any
_DUPLICATE_COUNTER: Any
_DEDUP_HIT_COUNTER: Any
_PROCESSING_DURATION_SECONDS: Any
_PHASE_DURATION_SECONDS: Any


def register_metrics() -> None:
    global _ITEM_OUTCOME_COUNTER
    global _RETRY_COUNTER
    global _FAILURE_COUNTER
    global _DUPLICATE_COUNTER
    global _DEDUP_HIT_COUNTER
    global _PROCESSING_DURATION_SECONDS
    global _PHASE_DURATION_SECONDS

    _ITEM_OUTCOME_COUNTER = counter(
        "download_flow_item_outcomes_total",
        "Number of download flow items by terminal state",
        label_names=("state",),
    )

    _RETRY_COUNTER = counter(
        "download_flow_item_retries_total",
        "Total number of download flow retries grouped by error type",
        label_names=("error_type",),
    )

    _FAILURE_COUNTER = counter(
        "download_flow_item_failures_total",
        "Total number of download flow failures grouped by error type",
        label_names=("error_type",),
    )

    _DUPLICATE_COUNTER = counter(
        "download_flow_duplicates_total",
        "Duplicate items encountered while processing download batches",
        label_names=("already_processed",),
    )

    _DEDUP_HIT_COUNTER = counter(
        "download_flow_dedupe_hits_total",
        "Duplicate items skipped because the payload was already processed",
    )

    _PROCESSING_DURATION_SECONDS = histogram(
        "download_flow_processing_seconds",
        "Total processing time per download flow item",
    )

    _PHASE_DURATION_SECONDS = histogram(
        "download_flow_phase_duration_seconds",
        "Download flow phase durations in seconds",
        label_names=("phase",),
    )


register_metrics()


def _error_type(error: Exception) -> str:
    return error.__class__.__name__


def _observe_phase_durations(events: Iterable[ItemEvent]) -> None:
    ordered = sorted(events, key=lambda event: event.timestamp)
    if not ordered:
        return

    first_seen: dict[str, datetime] = {}
    for event in ordered:
        first_seen.setdefault(event.name, event.timestamp)

    def _first(names: Iterable[str]) -> datetime | None:
        candidates = [first_seen[name] for name in names if name in first_seen]
        if not candidates:
            return None
        return min(candidates)

    download_start = _first(("download.accepted", "download.in_progress"))
    if download_start is None:
        download_start = _first(("download.detected", "download.completed"))
    download_end = _first(("download.detected", "download.completed"))
    if download_start and download_end and download_end >= download_start:
        duration = max((download_end - download_start).total_seconds(), 0.0)
        _PHASE_DURATION_SECONDS.labels(phase="download").observe(duration)

    tagging_end = _first(("tagging.completed", "tagging.skipped"))
    if download_end and tagging_end and tagging_end >= download_end:
        duration = max((tagging_end - download_end).total_seconds(), 0.0)
        _PHASE_DURATION_SECONDS.labels(phase="tagging").observe(duration)

    moving_end = _first(("file.moved",))
    if tagging_end and moving_end and moving_end >= tagging_end:
        duration = max((moving_end - tagging_end).total_seconds(), 0.0)
        _PHASE_DURATION_SECONDS.labels(phase="moving").observe(duration)


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values if value >= 0)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower_index = int(math.floor(rank))
    upper_index = int(math.ceil(rank))
    if lower_index == upper_index:
        return ordered[lower_index]
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    weight = rank - lower_index
    return lower + (upper - lower) * weight


@dataclass(slots=True)
class _BatchState:
    batch_id: str
    requested_by: str
    items_total: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_items: int = field(init=False)
    retries: int = 0
    dedupe_hits: int = 0
    duplicates: int = 0
    skipped: int = 0
    succeeded: int = 0
    failed: int = 0
    durations: list[float] = field(default_factory=list)
    results: dict[str, DownloadItemResult] = field(default_factory=dict)
    completed_event: asyncio.Event = field(default_factory=asyncio.Event)
    summary: BatchSummary | None = None

    def __post_init__(self) -> None:
        self.pending_items = self.items_total


class DownloadBatchAggregator:
    """Track per-batch state and emit structured telemetry."""

    def __init__(self) -> None:
        self._batches: dict[str, _BatchState] = {}

    def create_batch(self, batch_id: str, *, requested_by: str, total: int) -> _BatchState:
        state = _BatchState(batch_id=batch_id, requested_by=requested_by, items_total=total)
        self._batches[batch_id] = state
        return state

    def get_batch(self, batch_id: str) -> _BatchState:
        return self._batches[batch_id]

    async def record_queued(self, state: _BatchState, item: DownloadItem) -> None:
        await self._append_result(
            state,
            DownloadItemResult(
                item_id=item.item_id,
                batch_id=item.batch_id,
                state=ItemState.QUEUED,
                attempts=0,
                final_path=None,
                tags_written=False,
                bytes_written=None,
                duration_seconds=None,
                quality=None,
                error=None,
                events=(),
            ),
            replace=False,
        )
        log_event(
            _logger,
            "download_flow.request.sent",
            component="download_flow",
            batch_id=item.batch_id,
            item_id=item.item_id,
            dedupe_key=item.dedupe_key,
            priority=item.priority,
        )

    async def record_duplicate(
        self,
        state: _BatchState,
        item: DownloadItem,
        *,
        reason: str,
        already_processed: bool,
    ) -> None:
        async with state.lock:
            state.duplicates += 1
            if already_processed:
                state.dedupe_hits += 1
            state.pending_items -= 1
            result = DownloadItemResult(
                item_id=item.item_id,
                batch_id=item.batch_id,
                state=ItemState.DUPLICATE,
                attempts=0,
                final_path=None,
                tags_written=False,
                bytes_written=None,
                duration_seconds=None,
                quality=None,
                error=reason,
                events=(
                    ItemEvent(
                        name="duplicate.skipped",
                        timestamp=datetime.now(timezone.utc),
                        meta={"reason": reason},
                    ),
                ),
            )
            state.results[item.item_id] = result
            if state.pending_items <= 0:
                await self._finalise(state)
        already_processed_label = "true" if already_processed else "false"
        _DUPLICATE_COUNTER.labels(already_processed=already_processed_label).inc()
        if already_processed:
            _DEDUP_HIT_COUNTER.inc()
        _ITEM_OUTCOME_COUNTER.labels(state=ItemState.DUPLICATE.value).inc()
        log_event(
            _logger,
            "download_flow.duplicate.skipped",
            component="download_flow",
            batch_id=item.batch_id,
            item_id=item.item_id,
            dedupe_key=item.dedupe_key,
            reason=reason,
        )

    async def record_retry(
        self,
        state: _BatchState,
        item: DownloadItem,
        *,
        attempt: int,
        error: Exception,
        retry_after: float | None,
    ) -> None:
        async with state.lock:
            state.retries += 1
            result = state.results.get(item.item_id)
            if result is not None:
                events = list(result.events)
            else:
                events = []
            events.append(
                ItemEvent(
                    name="failure.retry",
                    timestamp=datetime.now(timezone.utc),
                    meta={
                        "attempt": attempt,
                        "retry_after_seconds": retry_after,
                        "error": str(error),
                    },
                )
            )
            state.results[item.item_id] = DownloadItemResult(
                item_id=item.item_id,
                batch_id=item.batch_id,
                state=ItemState.DOWNLOADING,
                attempts=attempt,
                final_path=None,
                tags_written=False,
                bytes_written=None,
                duration_seconds=None,
                quality=None,
                error=str(error),
                events=tuple(events),
            )
        _RETRY_COUNTER.labels(error_type=_error_type(error)).inc()
        log_event(
            _logger,
            "download_flow.failure.retry",
            component="download_flow",
            batch_id=item.batch_id,
            item_id=item.item_id,
            attempt=attempt,
            retry_after_seconds=retry_after,
        )

    async def record_success(
        self,
        state: _BatchState,
        item: DownloadItem,
        *,
        outcome: DownloadOutcome,
        attempts: int,
        processing_seconds: float,
        events: Iterable[ItemEvent],
    ) -> None:
        event_list = list(events)
        names = {event.name for event in event_list}
        now = datetime.now(timezone.utc)
        if "download.completed" not in names:
            event_list.append(
                ItemEvent(
                    name="download.completed",
                    timestamp=now,
                    meta={"final_path": str(outcome.final_path)},
                )
            )
        async with state.lock:
            state.succeeded += 1
            state.pending_items -= 1
            state.durations.append(max(processing_seconds, 0.0))
            result = DownloadItemResult(
                item_id=item.item_id,
                batch_id=item.batch_id,
                state=ItemState.DONE,
                attempts=attempts,
                final_path=outcome.final_path,
                tags_written=outcome.tags_written,
                bytes_written=outcome.bytes_written,
                duration_seconds=outcome.track_duration_seconds,
                quality=outcome.quality,
                error=None,
                events=tuple(event_list),
            )
            state.results[item.item_id] = result
            if state.pending_items <= 0:
                await self._finalise(state)
        _ITEM_OUTCOME_COUNTER.labels(state=ItemState.DONE.value).inc()
        _PROCESSING_DURATION_SECONDS.observe(max(processing_seconds, 0.0))
        _observe_phase_durations(event_list)
        log_event(
            _logger,
            "download_flow.download.completed",
            component="download_flow",
            batch_id=item.batch_id,
            item_id=item.item_id,
            attempts=attempts,
            final_path=str(outcome.final_path),
        )
        for event in event_list:
            if event.name == "download.completed":
                continue
            log_event(
                _logger,
                f"download_flow.{event.name}",
                component="download_flow",
                batch_id=item.batch_id,
                item_id=item.item_id,
                meta=dict(event.meta) if event.meta is not None else None,
            )

    async def record_failure(
        self,
        state: _BatchState,
        item: DownloadItem,
        *,
        attempts: int,
        error: Exception,
        processing_seconds: float,
    ) -> None:
        async with state.lock:
            state.failed += 1
            state.pending_items -= 1
            state.durations.append(max(processing_seconds, 0.0))
            result = DownloadItemResult(
                item_id=item.item_id,
                batch_id=item.batch_id,
                state=ItemState.FAILED,
                attempts=attempts,
                final_path=None,
                tags_written=False,
                bytes_written=None,
                duration_seconds=None,
                quality=None,
                error=str(error),
                events=(
                    ItemEvent(
                        name="download.failed",
                        timestamp=datetime.now(timezone.utc),
                        meta={"error": str(error), "attempts": attempts},
                    ),
                ),
            )
            state.results[item.item_id] = result
            if state.pending_items <= 0:
                await self._finalise(state)
        _ITEM_OUTCOME_COUNTER.labels(state=ItemState.FAILED.value).inc()
        _FAILURE_COUNTER.labels(error_type=_error_type(error)).inc()
        _PROCESSING_DURATION_SECONDS.observe(max(processing_seconds, 0.0))
        log_event(
            _logger,
            "download_flow.download.failed",
            component="download_flow",
            batch_id=item.batch_id,
            item_id=item.item_id,
            attempts=attempts,
            error=str(error),
        )

    async def _append_result(
        self,
        state: _BatchState,
        result: DownloadItemResult,
        *,
        replace: bool = True,
    ) -> None:
        async with state.lock:
            if replace or result.item_id not in state.results:
                state.results[result.item_id] = result

    async def _finalise(self, state: _BatchState) -> None:
        if state.summary is not None:
            return
        completed_at = datetime.now(timezone.utc)
        durations = list(state.durations)
        p95 = _percentile(durations, 0.95)
        p99 = _percentile(durations, 0.99)
        totals = BatchTotals(
            total_items=state.items_total,
            succeeded=state.succeeded,
            failed=state.failed,
            duplicates=state.duplicates,
            skipped=state.skipped,
            retries=state.retries,
            dedupe_hits=state.dedupe_hits,
        )
        if state.failed == 0:
            status = BatchStatus.SUCCESS
        elif state.succeeded == 0:
            status = BatchStatus.FAILED
        else:
            status = BatchStatus.PARTIAL_SUCCESS
        state.summary = BatchSummary(
            batch_id=state.batch_id,
            status=status,
            requested_by=state.requested_by,
            created_at=state.created_at,
            completed_at=completed_at,
            totals=totals,
            durations=DurationStats(
                total_seconds=(completed_at - state.created_at).total_seconds(),
                p95_seconds=p95,
                p99_seconds=p99,
            ),
            items=tuple(state.results.values()),
        )
        state.completed_event.set()

    async def wait_for_summary(self, batch_id: str) -> BatchSummary:
        state = self._batches[batch_id]
        await state.completed_event.wait()
        assert state.summary is not None  # defensive: summary must be set when event fires
        return state.summary
