from __future__ import annotations

import warnings

from app.hdm.recovery import DownloadSidecar, HdmRecovery, SidecarStore

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.recovery instead.",
    DeprecationWarning,
    stacklevel=2,
)

DownloadFlowRecovery = HdmRecovery

__all__ = [
    "DownloadFlowRecovery",
    "DownloadSidecar",
    "HdmRecovery",
    "SidecarStore",
]
