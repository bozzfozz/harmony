"""Download flow orchestrator package."""

from .controller import BatchHandle, DownloadFlowOrchestrator
from .idempotency import IdempotencyReservation, IdempotencyStore, InMemoryIdempotencyStore
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
from .pipeline import DownloadPipeline, DownloadPipelineError, RetryableDownloadError

__all__ = [
    "BatchHandle",
    "BatchStatus",
    "BatchSummary",
    "BatchTotals",
    "DownloadBatchRequest",
    "DownloadFlowOrchestrator",
    "DownloadItem",
    "DownloadItemResult",
    "DownloadOutcome",
    "DownloadPipeline",
    "DownloadPipelineError",
    "DownloadRequestItem",
    "DownloadWorkItem",
    "DurationStats",
    "IdempotencyReservation",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "ItemEvent",
    "ItemState",
    "RetryableDownloadError",
]
