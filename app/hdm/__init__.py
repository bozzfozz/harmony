"""Harmony Download Manager (HDM) package."""

from .idempotency import (
    IdempotencyReservation,
    IdempotencyStore,
    InMemoryIdempotencyStore,
)
from .models import (
    BatchStatus,
    BatchSummary,
    BatchTotals,
    DownloadBatchRequest,
    DownloadItem,
    DownloadItemResult,
    DownloadOutcome,
    DownloadRequestItem,
    DownloadWorkItem,
    DurationStats,
    ItemEvent,
    ItemState,
)
from .move import AtomicFileMover
from .orchestrator import BatchHandle, HdmOrchestrator
from .pipeline import DownloadPipeline, DownloadPipelineError, RetryableDownloadError

__all__ = [
    "AtomicFileMover",
    "BatchHandle",
    "BatchStatus",
    "BatchSummary",
    "BatchTotals",
    "DownloadBatchRequest",
    "DownloadItem",
    "DownloadItemResult",
    "DownloadOutcome",
    "DownloadPipeline",
    "DownloadPipelineError",
    "DownloadRequestItem",
    "DownloadWorkItem",
    "DurationStats",
    "HdmOrchestrator",
    "IdempotencyReservation",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "ItemEvent",
    "ItemState",
    "RetryableDownloadError",
]
