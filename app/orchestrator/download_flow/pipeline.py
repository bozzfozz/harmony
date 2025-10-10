"""Protocol and error hierarchy for the download pipeline."""

from __future__ import annotations

from typing import Protocol

from .models import DownloadOutcome, DownloadWorkItem


class DownloadPipeline(Protocol):
    """A pipeline that downloads, enriches and moves a single item."""

    async def execute(self, work_item: DownloadWorkItem) -> DownloadOutcome:
        """Process the supplied work item and return its outcome."""


class DownloadPipelineError(RuntimeError):
    """Base error raised for unrecoverable pipeline failures."""


class RetryableDownloadError(DownloadPipelineError):
    """Error raised when the pipeline should be retried for the same item."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
