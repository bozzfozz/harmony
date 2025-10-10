from __future__ import annotations

import warnings

from app.hdm.models import (
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

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.models instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "BatchStatus",
    "BatchSummary",
    "BatchTotals",
    "DownloadBatchRequest",
    "DownloadItem",
    "DownloadItemResult",
    "DownloadOutcome",
    "DownloadRequestItem",
    "DownloadWorkItem",
    "DurationStats",
    "ItemEvent",
    "ItemState",
]
