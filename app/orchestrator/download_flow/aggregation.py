from __future__ import annotations

import warnings

from app.hdm.aggregation import DownloadBatchAggregator, register_metrics

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.aggregation instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["DownloadBatchAggregator", "register_metrics"]
