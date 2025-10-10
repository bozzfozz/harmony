from __future__ import annotations

import warnings

from app.hdm.pipeline_impl import DefaultDownloadPipeline

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.pipeline_impl instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["DefaultDownloadPipeline"]
