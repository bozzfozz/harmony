"""Entry point for the Harmony FastAPI application."""

from __future__ import annotations

import inspect
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.config import AppConfig
from app.core.config import DEFAULT_SETTINGS
from app.dependencies import (
    get_app_config,
    get_matching_engine,
    get_soulseek_client,
    get_spotify_client,
)
from app.db import init_db
from app.logging import configure_logging, get_logger
from app.routers import (
    activity_router,
    backfill_router,
    download_router,
    free_ingest_router,
    health_router,
    imports_router,
    matching_router,
    metadata_router,
    search_router,
    settings_router,
    soulseek_router,
    spotify_free_router,
    spotify_router,
    sync_router,
    system_router,
    watchlist_router,
)
from app.services.backfill_service import BackfillService
from app.utils.activity import activity_manager
from app.utils.settings_store import ensure_default_settings
from app.workers import (
    ArtworkWorker,
    BackfillWorker,
    LyricsWorker,
    MatchingWorker,
    MetadataWorker,
    PlaylistSyncWorker,
    SyncWorker,
    WatchlistWorker,
)
from app.workers.retry_scheduler import RetryScheduler

logger = get_logger(__name__)


def _should_start_workers() -> bool:
    return os.getenv("HARMONY_DISABLE_WORKERS") not in {"1", "true", "TRUE"}


def _resolve_watchlist_interval(raw_value: str | None) -> float:
    default = 86_400.0
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid WATCHLIST_INTERVAL value %s; falling back to default",
            raw_value,
        )
        return default


def _configure_application(config: AppConfig) -> None:
    configure_logging(config.logging.level)
    init_db()
    ensure_default_settings(DEFAULT_SETTINGS)
    logger.info("Database initialised")
    activity_manager.refresh_cache()


async def _start_background_workers(
    app: FastAPI,
    config: AppConfig,
    *,
    enable_artwork: bool,
    enable_lyrics: bool,
) -> dict[str, bool]:
    soulseek_client = get_soulseek_client()
    matching_engine = get_matching_engine()
    spotify_client = get_spotify_client()

    state = app.state
    worker_status: dict[str, bool] = {
        "artwork": False,
        "lyrics": False,
        "metadata": False,
        "sync": False,
        "retry_scheduler": False,
        "matching": False,
        "playlist_sync": False,
        "backfill": False,
        "watchlist": False,
    }

    state.artwork_worker = None
    if enable_artwork:
        state.artwork_worker = ArtworkWorker(
            spotify_client=spotify_client,
            soulseek_client=soulseek_client,
            config=config.artwork,
        )
        await state.artwork_worker.start()
        worker_status["artwork"] = True

    state.lyrics_worker = None
    if enable_lyrics:
        state.lyrics_worker = LyricsWorker(spotify_client=spotify_client)
        await state.lyrics_worker.start()
        worker_status["lyrics"] = True

    state.rich_metadata_worker = MetadataWorker(
        spotify_client=spotify_client,
    )
    await state.rich_metadata_worker.start()
    worker_status["metadata"] = True

    state.sync_worker = SyncWorker(
        soulseek_client,
        metadata_worker=state.rich_metadata_worker,
        artwork_worker=state.artwork_worker,
        lyrics_worker=state.lyrics_worker,
    )
    await state.sync_worker.start()
    worker_status["sync"] = True

    state.retry_scheduler = RetryScheduler(state.sync_worker)
    await state.retry_scheduler.start()
    worker_status["retry_scheduler"] = True

    state.matching_worker = MatchingWorker(matching_engine)
    await state.matching_worker.start()
    worker_status["matching"] = True

    state.playlist_worker = PlaylistSyncWorker(spotify_client)
    await state.playlist_worker.start()
    worker_status["playlist_sync"] = True

    state.backfill_service = BackfillService(config.spotify, spotify_client)
    state.backfill_worker = BackfillWorker(state.backfill_service)
    await state.backfill_worker.start()
    worker_status["backfill"] = True

    interval_seconds = _resolve_watchlist_interval(os.getenv("WATCHLIST_INTERVAL"))
    state.watchlist_worker = WatchlistWorker(
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        sync_worker=state.sync_worker,
        interval_seconds=interval_seconds,
    )
    await state.watchlist_worker.start()
    worker_status["watchlist"] = True

    state.metadata_worker = None
    return worker_status


async def _stop_worker(worker: Any) -> None:
    if worker is None:
        return
    stop = getattr(worker, "stop", None)
    if not callable(stop):
        return
    result = stop()
    if inspect.isawaitable(result):
        await result


async def _stop_background_workers(app: FastAPI) -> None:
    state = app.state
    for attribute in [
        "artwork_worker",
        "lyrics_worker",
        "rich_metadata_worker",
        "retry_scheduler",
        "sync_worker",
        "matching_worker",
        "playlist_worker",
        "backfill_worker",
        "watchlist_worker",
        "metadata_worker",
    ]:
        await _stop_worker(getattr(state, attribute, None))
        if hasattr(state, attribute):
            delattr(state, attribute)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = get_app_config()
    _configure_application(config)

    feature_flags = config.features
    app.state.feature_flags = feature_flags

    enable_artwork = feature_flags.enable_artwork
    enable_lyrics = feature_flags.enable_lyrics

    worker_status: dict[str, bool] = {}

    if _should_start_workers():
        worker_status = await _start_background_workers(
            app,
            config,
            enable_artwork=enable_artwork,
            enable_lyrics=enable_lyrics,
        )
    else:
        logger.info("Background workers disabled via HARMONY_DISABLE_WORKERS")

    router_status = {
        "spotify": True,
        "spotify_backfill": True,
        "spotify_free": True,
        "free_ingest": True,
        "imports": True,
        "soulseek": True,
        "matching": True,
        "settings": True,
        "metadata": True,
        "search": True,
        "sync": True,
        "system": True,
        "downloads": True,
        "activity": True,
        "health": True,
        "watchlist": True,
    }

    flag_status = {
        "artwork": enable_artwork,
        "lyrics": enable_lyrics,
    }

    logger.info(
        "wiring_summary routers=%s workers=%s flags=%s integrations=spotify=true soulseek=true plex=false beets=false",
        router_status,
        worker_status,
        flag_status,
        extra={
            "event": "wiring_summary",
            "routers": router_status,
            "workers": worker_status,
            "flags": flag_status,
            "integrations": {
                "spotify": True,
                "soulseek": True,
                "plex": False,
                "beets": False,
            },
        },
    )

    logger.info("Harmony application started")
    try:
        yield
    finally:
        await _stop_background_workers(app)
        logger.info("Harmony application stopped")


app = FastAPI(title="Harmony Backend", version="1.4.0", lifespan=lifespan)

app.include_router(spotify_router, prefix="/spotify", tags=["Spotify"])
app.include_router(backfill_router, prefix="/spotify/backfill", tags=["Spotify Backfill"])
app.include_router(spotify_free_router)
app.include_router(free_ingest_router)
app.include_router(imports_router)
app.include_router(soulseek_router, prefix="/soulseek", tags=["Soulseek"])
app.include_router(matching_router, prefix="/matching", tags=["Matching"])
app.include_router(settings_router, prefix="/settings", tags=["Settings"])
app.include_router(metadata_router, tags=["Metadata"])
app.include_router(search_router, tags=["Search"])
app.include_router(sync_router, tags=["Sync"])
app.include_router(system_router, tags=["System"])
app.include_router(download_router)
app.include_router(activity_router)
app.include_router(health_router, prefix="/api/health", tags=["Health"])
app.include_router(watchlist_router, tags=["Watchlist"])


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "version": app.version}
