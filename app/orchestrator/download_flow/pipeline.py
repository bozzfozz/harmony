from __future__ import annotations

import warnings

from app.hdm.pipeline import DownloadPipeline, DownloadPipelineError, RetryableDownloadError

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.pipeline instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["DownloadPipeline", "DownloadPipelineError", "RetryableDownloadError"]
