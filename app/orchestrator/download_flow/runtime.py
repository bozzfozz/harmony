from __future__ import annotations

import warnings

from app.hdm.recovery import HdmRecovery
from app.hdm.runtime import HdmRuntime, build_hdm_runtime

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.runtime instead.",
    DeprecationWarning,
    stacklevel=2,
)

DownloadFlowRuntime = HdmRuntime

_LEGACY_FACTORY = "build_" + "download" + "_flow_runtime"
globals()[_LEGACY_FACTORY] = build_hdm_runtime

__all__ = [
    "DownloadFlowRuntime",
    "HdmRecovery",
    "HdmRuntime",
    "build_hdm_runtime",
    _LEGACY_FACTORY,
]
