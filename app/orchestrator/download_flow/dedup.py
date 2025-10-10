from __future__ import annotations

import warnings

from app.hdm.dedup import DeduplicationManager

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.dedup instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["DeduplicationManager"]
