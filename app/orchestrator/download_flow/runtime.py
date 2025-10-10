"""Runtime helpers for wiring the download flow orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import DownloadFlowConfig
from app.logging import get_logger

from .controller import DownloadFlowOrchestrator
from .idempotency import IdempotencyStore, InMemoryIdempotencyStore
from .pipeline import DownloadOutcome, DownloadPipeline, DownloadPipelineError, DownloadWorkItem

logger = get_logger(__name__)


class StubDownloadPipeline(DownloadPipeline):
    """Temporary pipeline implementation until FLOW-002 is fully implemented."""

    def __init__(self, *, downloads_dir: Path, music_dir: Path) -> None:
        self._downloads_dir = downloads_dir
        self._music_dir = music_dir

    async def execute(self, work_item: DownloadWorkItem) -> DownloadOutcome:  # type: ignore[override]
        logger.error(
            "Download flow pipeline invoked without an implementation",
            extra={
                "event": "download_flow.pipeline_unimplemented",
                "downloads_dir": str(self._downloads_dir),
                "music_dir": str(self._music_dir),
                "batch_id": work_item.item.batch_id,
                "item_id": work_item.item.item_id,
            },
        )
        raise DownloadPipelineError("Download flow pipeline is not yet configured")


class DownloadFlowRecovery:
    """Placeholder recovery controller for FLOW-002 orchestration."""

    def __init__(self, *, size_stable_seconds: int) -> None:
        self._size_stable_seconds = size_stable_seconds
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        logger.info(
            "Download flow recovery started",
            extra={
                "event": "download_flow.recovery_started",
                "size_stable_seconds": self._size_stable_seconds,
            },
        )

    async def shutdown(self) -> None:
        if not self._started:
            return
        self._started = False
        logger.info(
            "Download flow recovery stopped",
            extra={"event": "download_flow.recovery_stopped"},
        )


@dataclass(slots=True)
class DownloadFlowRuntime:
    """Container for the download flow orchestrator runtime."""

    orchestrator: DownloadFlowOrchestrator
    pipeline: DownloadPipeline
    idempotency_store: IdempotencyStore
    recovery: DownloadFlowRecovery


def build_download_flow_runtime(config: DownloadFlowConfig) -> DownloadFlowRuntime:
    """Initialise download flow components using the supplied configuration."""

    downloads_dir = Path(config.downloads_dir).expanduser().resolve()
    music_dir = Path(config.music_dir).expanduser().resolve()

    pipeline = StubDownloadPipeline(downloads_dir=downloads_dir, music_dir=music_dir)
    idempotency_store: IdempotencyStore = InMemoryIdempotencyStore()
    orchestrator = DownloadFlowOrchestrator(
        pipeline=pipeline,
        idempotency_store=idempotency_store,
        worker_concurrency=config.worker_concurrency,
        max_retries=config.max_retries,
        batch_max_items=config.batch_max_items,
    )
    recovery = DownloadFlowRecovery(size_stable_seconds=config.size_stable_seconds)

    return DownloadFlowRuntime(
        orchestrator=orchestrator,
        pipeline=pipeline,
        idempotency_store=idempotency_store,
        recovery=recovery,
    )


__all__ = [
    "DownloadFlowRecovery",
    "DownloadFlowRuntime",
    "StubDownloadPipeline",
    "build_download_flow_runtime",
]

