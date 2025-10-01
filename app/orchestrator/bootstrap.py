"""Bootstrap helpers for orchestrator runtime wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.dependencies import get_app_config, get_matching_engine, get_soulseek_client, get_spotify_client
from app.orchestrator.dispatcher import Dispatcher, JobHandler, default_handlers
from app.orchestrator.scheduler import Scheduler
from app.orchestrator.handlers import ArtworkService, LyricsService, MetadataService
from app.orchestrator.providers import (
    build_matching_handler_deps,
    build_retry_handler_deps,
    build_sync_handler_deps,
    build_watchlist_handler_deps,
)


@dataclass(slots=True)
class OrchestratorRuntime:
    """Container bundling orchestrator components and resolved dependencies."""

    scheduler: Scheduler
    dispatcher: Dispatcher
    handlers: Mapping[str, JobHandler]


def bootstrap_orchestrator(
    *,
    metadata_service: MetadataService | None = None,
    artwork_service: ArtworkService | None = None,
    lyrics_service: LyricsService | None = None,
) -> OrchestratorRuntime:
    """Initialise orchestrator components with shared dependencies."""

    config = get_app_config()
    soulseek_client = get_soulseek_client()
    spotify_client = get_spotify_client()
    matching_engine = get_matching_engine()

    sync_deps = build_sync_handler_deps(
        soulseek_client=soulseek_client,
        metadata_service=metadata_service,
        artwork_service=artwork_service,
        lyrics_service=lyrics_service,
    )
    matching_deps = build_matching_handler_deps(engine=matching_engine)
    retry_deps = build_retry_handler_deps()
    watchlist_deps = build_watchlist_handler_deps(
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        config=config.watchlist,
    )

    scheduler = Scheduler()
    handlers = default_handlers(
        sync_deps,
        matching_deps=matching_deps,
        retry_deps=retry_deps,
        watchlist_deps=watchlist_deps,
    )
    dispatcher = Dispatcher(scheduler, handlers)

    return OrchestratorRuntime(
        scheduler=scheduler,
        dispatcher=dispatcher,
        handlers=handlers,
    )


__all__ = ["OrchestratorRuntime", "bootstrap_orchestrator"]
