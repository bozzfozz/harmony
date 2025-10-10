"""Data models and enums for the download/enrich/move flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


class ItemState(str, Enum):
    """Lifecycle states for a download pipeline item."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    ENRICHING = "enriching"
    MOVING = "moving"
    DONE = "done"
    FAILED = "failed"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"


class BatchStatus(str, Enum):
    """Aggregated terminal state for a batch submission."""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


@dataclass(slots=True)
class DownloadRequestItem:
    """Represents a user supplied download request for a single track."""

    artist: str
    title: str
    album: str | None = None
    isrc: str | None = None
    duration_seconds: float | None = None
    bitrate: int | None = None
    priority: int | None = None
    dedupe_key: str | None = None
    requested_by: str | None = None


@dataclass(slots=True)
class DownloadBatchRequest:
    """Request envelope for a batch (or single) download flow submission."""

    items: Sequence[DownloadRequestItem]
    requested_by: str
    batch_id: str | None = None
    priority: int | None = None
    dedupe_key: str | None = None


@dataclass(slots=True)
class DownloadItem:
    """Normalised and enriched item tracked by the orchestrator."""

    batch_id: str
    item_id: str
    artist: str
    title: str
    album: str | None
    isrc: str | None
    requested_by: str
    priority: int
    dedupe_key: str
    duration_seconds: float | None = None
    bitrate: int | None = None
    index: int | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(slots=True)
class ItemEvent:
    """Structured event emitted during item processing."""

    name: str
    timestamp: datetime
    meta: Mapping[str, Any] | None = None


@dataclass(slots=True)
class DownloadOutcome:
    """Result produced by the download pipeline for a single item."""

    final_path: Path
    tags_written: bool
    bytes_written: int
    track_duration_seconds: float | None
    quality: str | None
    events: Sequence[ItemEvent] = field(default_factory=tuple)


@dataclass(slots=True)
class DownloadItemResult:
    """Terminal result for an item after orchestration completes."""

    item_id: str
    batch_id: str
    state: ItemState
    attempts: int
    final_path: Path | None
    tags_written: bool
    bytes_written: int | None
    duration_seconds: float | None
    quality: str | None
    error: str | None
    events: tuple[ItemEvent, ...]


@dataclass(slots=True)
class BatchTotals:
    """Aggregate counters summarising a batch submission."""

    total_items: int
    succeeded: int
    failed: int
    duplicates: int
    skipped: int
    retries: int
    dedupe_hits: int


@dataclass(slots=True)
class DurationStats:
    """Simple duration metrics for a batch."""

    total_seconds: float
    p95_seconds: float
    p99_seconds: float


@dataclass(slots=True)
class BatchSummary:
    """Completed batch summary returned to callers."""

    batch_id: str
    status: BatchStatus
    requested_by: str
    created_at: datetime
    completed_at: datetime
    totals: BatchTotals
    durations: DurationStats
    items: tuple[DownloadItemResult, ...]


@dataclass(slots=True)
class DownloadWorkItem:
    """Context object handed to the pipeline implementation."""

    item: DownloadItem
    attempt: int
    events: list[ItemEvent] = field(default_factory=list)

    def record_event(
        self,
        name: str,
        *,
        meta: Mapping[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Append a pipeline event with sensible defaults."""

        event_ts = timestamp or datetime.now(timezone.utc)
        self.events.append(ItemEvent(name=name, timestamp=event_ts, meta=meta))
