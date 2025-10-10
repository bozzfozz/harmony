from __future__ import annotations

import warnings

from app.hdm.orchestrator import BatchHandle, HdmOrchestrator

warnings.warn(
    f"{__name__} is deprecated; import from app.hdm.orchestrator instead.",
    DeprecationWarning,
    stacklevel=2,
)

DownloadFlowOrchestrator = HdmOrchestrator

__all__ = ["BatchHandle", "DownloadFlowOrchestrator", "HdmOrchestrator"]
