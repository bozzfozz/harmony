"""Runtime helpers for wiring the HDM orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import HdmConfig, SoulseekConfig
from app.integrations.slskd_client import SlskdHttpClient

from .completion import CompletionEventBus, DownloadCompletionMonitor
from .dedup import DeduplicationManager
from .idempotency import IdempotencyStore, InMemoryIdempotencyStore
from .move import AtomicFileMover
from .pipeline import DownloadPipeline
from .pipeline_impl import DefaultDownloadPipeline
from .recovery import HdmRecovery, SidecarStore
from .orchestrator import HdmOrchestrator
from .tagging import AudioTagger


@dataclass(slots=True)
class HdmRuntime:
    """Container for the HDM orchestrator runtime."""

    orchestrator: HdmOrchestrator
    pipeline: DownloadPipeline
    idempotency_store: IdempotencyStore
    recovery: HdmRecovery


def build_hdm_runtime(
    config: HdmConfig, soulseek: SoulseekConfig
) -> HdmRuntime:
    """Initialise HDM components using the supplied configuration."""

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

    slskd_client = SlskdHttpClient(
        base_url=soulseek.base_url,
        api_key=soulseek.api_key,
        timeout_ms=config.slskd_timeout_seconds * 1000,
        max_attempts=max(1, config.max_retries),
        backoff_base_ms=soulseek.retry_backoff_base_ms,
        jitter_pct=int(round(soulseek.retry_jitter_pct)),
    )

    pipeline: DownloadPipeline = DefaultDownloadPipeline(
        completion_monitor=completion_monitor,
        tagger=tagger,
        mover=mover,
        deduper=deduper,
        sidecars=sidecar_store,
        slskd_client=slskd_client,
        status_poll_interval=1.0,
    )

    idempotency_store: IdempotencyStore = InMemoryIdempotencyStore()
    orchestrator = HdmOrchestrator(
        pipeline=pipeline,
        idempotency_store=idempotency_store,
        worker_concurrency=config.worker_concurrency,
        max_retries=config.max_retries,
        batch_max_items=config.batch_max_items,
    )
    recovery = HdmRecovery(
        size_stable_seconds=config.size_stable_seconds,
        sidecars=sidecar_store,
        completion_monitor=completion_monitor,
        event_bus=event_bus,
    )

    return HdmRuntime(
        orchestrator=orchestrator,
        pipeline=pipeline,
        idempotency_store=idempotency_store,
        recovery=recovery,
    )


__all__ = [
    "HdmRecovery",
    "HdmRuntime",
    "build_hdm_runtime",
]

