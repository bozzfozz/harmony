"""Runtime helpers for wiring the download flow orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import DownloadFlowConfig

from .completion import CompletionEventBus, DownloadCompletionMonitor
from .controller import DownloadFlowOrchestrator
from .dedup import DeduplicationManager
from .idempotency import IdempotencyStore, InMemoryIdempotencyStore
from .move import AtomicFileMover
from .pipeline import DownloadPipeline
from .pipeline_impl import DefaultDownloadPipeline
from .recovery import DownloadFlowRecovery, SidecarStore
from .tagging import AudioTagger


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

    downloads_dir.mkdir(parents=True, exist_ok=True)
    music_dir.mkdir(parents=True, exist_ok=True)
    state_dir = downloads_dir / ".harmony"
    sidecar_store = SidecarStore(state_dir / "sidecars")
    event_bus = CompletionEventBus()
    completion_monitor = DownloadCompletionMonitor(
        downloads_dir=downloads_dir,
        size_stable_seconds=config.size_stable_seconds,
        event_bus=event_bus,
    )
    tagger = AudioTagger()
    mover = AtomicFileMover()
    deduper = DeduplicationManager(
        music_dir=music_dir,
        state_dir=state_dir,
        move_template=config.move_template,
    )

    pipeline: DownloadPipeline = DefaultDownloadPipeline(
        completion_monitor=completion_monitor,
        tagger=tagger,
        mover=mover,
        deduper=deduper,
        sidecars=sidecar_store,
    )

    idempotency_store: IdempotencyStore = InMemoryIdempotencyStore()
    orchestrator = DownloadFlowOrchestrator(
        pipeline=pipeline,
        idempotency_store=idempotency_store,
        worker_concurrency=config.worker_concurrency,
        max_retries=config.max_retries,
        batch_max_items=config.batch_max_items,
    )
    recovery = DownloadFlowRecovery(
        size_stable_seconds=config.size_stable_seconds,
        sidecars=sidecar_store,
        completion_monitor=completion_monitor,
        event_bus=event_bus,
    )

    return DownloadFlowRuntime(
        orchestrator=orchestrator,
        pipeline=pipeline,
        idempotency_store=idempotency_store,
        recovery=recovery,
    )


__all__ = [
    "DownloadFlowRecovery",
    "DownloadFlowRuntime",
    "build_download_flow_runtime",
]

