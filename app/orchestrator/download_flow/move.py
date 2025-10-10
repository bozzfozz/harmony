from __future__ import annotations

import warnings

from app.hdm.move import AtomicFileMover

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.move instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["AtomicFileMover"]
