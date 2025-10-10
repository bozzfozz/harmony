from __future__ import annotations

import warnings

from app.hdm.tagging import AudioTagger, TaggingResult

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.tagging instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["AudioTagger", "TaggingResult"]
