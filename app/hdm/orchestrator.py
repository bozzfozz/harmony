"""Harmony Download Manager orchestrator coordinating batch submissions and workers."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import random
import time
import uuid

from app.logging import get_logger

from .aggregation import DownloadBatchAggregator
from .idempotency import IdempotencyStore
from .models import (
    BatchSummary,
    DownloadBatchRequest,
    DownloadItem,
    DownloadRequestItem,
    DownloadWorkItem,
)
from .pipeline import DownloadPipeline, DownloadPipelineError, RetryableDownloadError


@dataclass(slots=True)
class BatchHandle:
    """Handle returned to callers for awaiting batch completion."""

    batch_id: str
    items_total: int
    requested_by: str
    _aggregator: DownloadBatchAggregator

    async def wait(self) -> BatchSummary:
        """Wait until the batch has completed and return its summary."""

        return await self._aggregator.wait_for_summary(self.batch_id)


class _RoundRobinQueue:
    """Round robin queue ensuring fair scheduling across batches."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._queues: dict[str, deque[DownloadItem]] = {}
        self._order: deque[str] = deque()
        self._stopping = False

    async def put(self, item: DownloadItem) -> None:
        async with self._condition:
            queue = self._queues.setdefault(item.batch_id, deque())
            queue.append(item)
            if item.batch_id not in self._order:
                self._order.append(item.batch_id)
            self._condition.notify()

    async def get(self) -> DownloadItem | None:
        async with self._condition:
            while True:
                if self._stopping and not self._order:
                    return None
                if self._order:
                    batch_id = self._order[0]
                    queue = self._queues[batch_id]
                    item = queue.popleft()
                    if queue:
                        self._order.rotate(-1)
                    else:
                        self._order.popleft()
                        del self._queues[batch_id]
                    return item
                await self._condition.wait()

    async def stop(self) -> None:
        async with self._condition:
            self._stopping = True
            self._condition.notify_all()


class HdmOrchestrator:
    """Coordinate download, enrichment, and move jobs with bounded concurrency."""

    def __init__(
        self,
        *,
        pipeline: DownloadPipeline,
        idempotency_store: IdempotencyStore,
        worker_concurrency: int,
        max_retries: int,
        batch_max_items: int,
        retry_base_seconds: float = 0.5,
        retry_jitter_pct: float = 0.2,
        rng: random.Random | None = None,
    ) -> None:
        if worker_concurrency <= 0:
            raise ValueError("worker_concurrency must be positive")
        if max_retries <= 0:
            raise ValueError("max_retries must be positive")
        if batch_max_items <= 0:
            raise ValueError("batch_max_items must be positive")
        self._pipeline = pipeline
        self._idempotency = idempotency_store
        self._worker_concurrency = worker_concurrency
        self._max_retries = max_retries
        self._batch_max_items = batch_max_items
        self._retry_base_seconds = max(0.01, float(retry_base_seconds))
        self._retry_jitter_pct = max(0.0, float(retry_jitter_pct))
        self._rng = rng or random.Random()
        self._aggregator = DownloadBatchAggregator()
        self._queue = _RoundRobinQueue()
        self._workers: list[asyncio.Task[None]] = []
        self._started = False
        self._start_lock = asyncio.Lock()
        self._stopping = False
        self._logger = get_logger("hdm.orchestrator")

    async def start(self) -> None:
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            self._workers = [
                asyncio.create_task(self._worker_loop(index))
                for index in range(self._worker_concurrency)
            ]
            self._started = True

    async def shutdown(self) -> None:
        self._stopping = True
        await self._queue.stop()
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except asyncio.CancelledError:
                continue
        self._workers.clear()
        self._started = False

    async def submit_single(self, item: DownloadRequestItem) -> BatchHandle:
        if not item.requested_by:
            raise ValueError("requested_by is required for single submissions")
        request = DownloadBatchRequest(items=[item], requested_by=item.requested_by)
        return await self.submit_batch(request)

    async def submit_batch(self, request: DownloadBatchRequest) -> BatchHandle:
        if self._stopping:
            raise RuntimeError("orchestrator is shutting down")
        if not request.items:
            raise ValueError("batch request must contain at least one item")
        if len(request.items) > self._batch_max_items:
            raise ValueError("batch size exceeds configured limit")
        if not request.requested_by or not request.requested_by.strip():
            raise ValueError("requested_by is required")
        batch_id = request.batch_id or uuid.uuid4().hex
        normalised = [
            self._normalise_item(batch_id, request, index, item)
            for index, item in enumerate(request.items)
        ]
        await self.start()
        state = self._aggregator.create_batch(
            batch_id,
            requested_by=request.requested_by,
            total=len(normalised),
        )
        for item in normalised:
            await self._aggregator.record_queued(state, item)
            await self._queue.put(item)
        return BatchHandle(
            batch_id=batch_id,
            items_total=len(normalised),
            requested_by=request.requested_by,
            _aggregator=self._aggregator,
        )

    async def _worker_loop(self, worker_index: int) -> None:
        try:
            while True:
                item = await self._queue.get()
                if item is None:
                    return
                await self._process_item(item)
        except asyncio.CancelledError:
            return
        except Exception:  # pragma: no cover - defensive guard
            self._logger.exception(
                "HDM worker crashed",
                extra={"event": "hdm.worker.crashed", "worker": worker_index},
            )

    async def _process_item(self, item: DownloadItem) -> None:
        reservation = await self._idempotency.reserve(item)
        state = self._aggregator.get_batch(item.batch_id)
        if not reservation.acquired:
            await self._aggregator.record_duplicate(
                state,
                item,
                reason=reservation.reason or "duplicate",
                already_processed=reservation.already_processed,
            )
            return

        attempt = 1
        success = False
        try:
            while True:
                start = time.monotonic()
                work_item = DownloadWorkItem(item=item, attempt=attempt)
                try:
                    outcome = await self._pipeline.execute(work_item)
                except asyncio.CancelledError:
                    raise
                except RetryableDownloadError as retryable:
                    processing_seconds = time.monotonic() - start
                    await self._aggregator.record_retry(
                        state,
                        item,
                        attempt=attempt,
                        error=retryable,
                        retry_after=retryable.retry_after_seconds,
                    )
                    if attempt >= self._max_retries:
                        await self._aggregator.record_failure(
                            state,
                            item,
                            attempts=attempt,
                            error=retryable,
                            processing_seconds=processing_seconds,
                        )
                        return
                    backoff = self._compute_backoff(attempt, retryable.retry_after_seconds)
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue
                except DownloadPipelineError as fatal:
                    processing_seconds = time.monotonic() - start
                    await self._aggregator.record_failure(
                        state,
                        item,
                        attempts=attempt,
                        error=fatal,
                        processing_seconds=processing_seconds,
                    )
                    return
                except Exception as exc:
                    processing_seconds = time.monotonic() - start
                    await self._aggregator.record_failure(
                        state,
                        item,
                        attempts=attempt,
                        error=exc,
                        processing_seconds=processing_seconds,
                    )
                    return
                else:
                    events = list(work_item.events)
                    if outcome.events:
                        events.extend(outcome.events)
                    processing_seconds = time.monotonic() - start
                    await self._aggregator.record_success(
                        state,
                        item,
                        outcome=outcome,
                        attempts=attempt,
                        processing_seconds=processing_seconds,
                        events=events,
                    )
                    success = True
                    return
        finally:
            await self._idempotency.release(item, success=success)

    def _compute_backoff(self, attempt: int, retry_after: float | None) -> float:
        base = self._retry_base_seconds * (2 ** max(0, attempt - 1))
        jitter_fraction = self._rng.uniform(-self._retry_jitter_pct, self._retry_jitter_pct)
        delay = base * (1 + jitter_fraction)
        delay = max(0.0, delay)
        if retry_after is not None:
            delay = max(delay, retry_after)
        return delay

    def _normalise_item(
        self,
        batch_id: str,
        request: DownloadBatchRequest,
        index: int,
        item: DownloadRequestItem,
    ) -> DownloadItem:
        artist = item.artist.strip()
        title = item.title.strip()
        if not artist or not title:
            raise ValueError("artist and title are required for each item")
        album = item.album.strip() if item.album else None
        isrc = item.isrc.strip() if item.isrc else None
        requested_by = (item.requested_by or request.requested_by).strip()
        if not requested_by:
            requested_by = request.requested_by
        raw_priority = item.priority if item.priority is not None else request.priority
        try:
            priority = int(raw_priority) if raw_priority is not None else 0
        except (TypeError, ValueError):
            priority = 0
        dedupe_key = self._resolve_dedupe_key(
            item,
            batch_dedupe=request.dedupe_key,
        )
        return DownloadItem(
            batch_id=batch_id,
            item_id=uuid.uuid4().hex,
            artist=artist,
            title=title,
            album=album,
            isrc=isrc,
            requested_by=requested_by,
            priority=max(0, priority),
            dedupe_key=dedupe_key,
            duration_seconds=item.duration_seconds,
            bitrate=item.bitrate,
            index=index,
        )

    def _resolve_dedupe_key(
        self,
        item: DownloadRequestItem,
        *,
        batch_dedupe: str | None,
    ) -> str:
        if item.dedupe_key:
            base = item.dedupe_key.strip()
        elif item.isrc:
            base = item.isrc.strip().upper()
        else:
            components: list[str] = [
                item.artist.strip().lower(),
                item.title.strip().lower(),
            ]
            if item.album:
                components.append(item.album.strip().lower())
            base = "|".join(filter(None, components))
        if not base:
            base = uuid.uuid4().hex
        if batch_dedupe:
            return f"{batch_dedupe}:{base}"
        return base


__all__ = ["HdmOrchestrator", "BatchHandle"]
