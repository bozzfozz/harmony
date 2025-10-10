from __future__ import annotations

import warnings

from app.hdm.completion import (
    CompletionEventBus,
    CompletionResult,
    DownloadCompletionEvent,
    DownloadCompletionMonitor,
)

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.completion instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "CompletionEventBus",
    "CompletionResult",
    "DownloadCompletionEvent",
    "DownloadCompletionMonitor",
]
