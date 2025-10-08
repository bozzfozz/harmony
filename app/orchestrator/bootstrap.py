"""Bootstrap helpers for orchestrator runtime wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from app.dependencies import (get_app_config, get_matching_engine,
                              get_session_runner, get_soulseek_client,
                              get_spotify_client)
from app.orchestrator.dispatcher import (Dispatcher, JobHandler,
                                         default_handlers)
from app.orchestrator.handlers import (ARTIST_REFRESH_JOB_TYPE,
                                       ARTIST_SCAN_JOB_TYPE, ArtworkService,
                                       LyricsService, MetadataService)
from app.orchestrator.providers import (build_artist_delta_handler_deps,
                                        build_artist_refresh_handler_deps,
                                        build_artist_sync_handler_deps,
                                        build_matching_handler_deps,
                                        build_retry_handler_deps,
                                        build_sync_handler_deps,
                                        build_watchlist_handler_deps)
from app.orchestrator.scheduler import Scheduler
from app.services.free_ingest_service import FreeIngestService
from app.workers.import_worker import ImportWorker


@dataclass(slots=True)
class OrchestratorRuntime:
    """Container bundling orchestrator components and resolved dependencies."""

    scheduler: Scheduler
    dispatcher: Dispatcher
    handlers: Mapping[str, JobHandler]
    enabled_jobs: Mapping[str, bool]
    import_worker: Optional[ImportWorker]


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

    features = config.features
    if not features.enable_artwork:
        artwork_service = None
    if not features.enable_lyrics:
        lyrics_service = None

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
    artist_refresh_deps = build_artist_refresh_handler_deps(config=config.watchlist)
    artist_delta_deps = build_artist_delta_handler_deps(
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        config=config.watchlist,
    )
    artist_sync_deps = build_artist_sync_handler_deps()

    scheduler = Scheduler()
    handlers = default_handlers(
        sync_deps,
        matching_deps=matching_deps,
        retry_deps=retry_deps,
        watchlist_deps=watchlist_deps,
        artist_refresh_deps=artist_refresh_deps,
        artist_delta_deps=artist_delta_deps,
        artist_sync_deps=artist_sync_deps,
    )
    dispatcher = Dispatcher(scheduler, handlers)

    session_runner = get_session_runner()
    free_ingest_service = FreeIngestService(
        config=config,
        soulseek_client=soulseek_client,
        sync_worker=None,
        session_runner=session_runner,
    )
    import_worker = ImportWorker(free_ingest_service=free_ingest_service)

    enabled_jobs: dict[str, bool] = {}
    job_types = [
        "sync",
        "matching",
        "retry",
        "watchlist",
        ARTIST_REFRESH_JOB_TYPE,
        ARTIST_SCAN_JOB_TYPE,
        "artist_sync",
        "artist_delta",
    ]
    for job_type in job_types:
        enabled_jobs[job_type] = job_type in handlers
    enabled_jobs["artwork"] = bool(features.enable_artwork)
    enabled_jobs["lyrics"] = bool(features.enable_lyrics)

    return OrchestratorRuntime(
        scheduler=scheduler,
        dispatcher=dispatcher,
        handlers=handlers,
        enabled_jobs=enabled_jobs,
        import_worker=import_worker,
    )


__all__ = ["OrchestratorRuntime", "bootstrap_orchestrator"]
