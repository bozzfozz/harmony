"""Entry point for the Harmony FastAPI application."""

from __future__ import annotations

import inspect
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.config import AppConfig
from app.core.beets_client import BeetsClient
from app.core.config import DEFAULT_SETTINGS
from app.dependencies import (
    get_app_config,
    get_matching_engine,
    get_plex_client,
    get_soulseek_client,
    get_spotify_client,
)
from app.db import init_db, session_scope
from app.logging import configure_logging, get_logger
from app.models import ArtistPreference
from app.routers import (
    activity_router,
    backfill_router,
    beets_router,
    download_router,
    free_ingest_router,
    health_router,
    imports_router,
    matching_router,
    metadata_router,
    plex_router,
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
    AutoSyncWorker,
    BackfillWorker,
    DiscographyWorker,
    LyricsWorker,
    MatchingWorker,
    MetadataWorker,
    MetadataUpdateWorker,
    PlaylistSyncWorker,
    ScanWorker,
    SyncWorker,
    WatchlistWorker,
)
from app.workers.retry_scheduler import RetryScheduler
from sqlalchemy import select

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


async def _start_background_workers(app: FastAPI, config: AppConfig) -> None:
    soulseek_client = get_soulseek_client()
    matching_engine = get_matching_engine()
    plex_client = get_plex_client()
    spotify_client = get_spotify_client()
    beets_client = BeetsClient()

    state = app.state
    state.artwork_worker = ArtworkWorker(
        spotify_client=spotify_client,
        plex_client=plex_client,
        soulseek_client=soulseek_client,
        beets_client=beets_client,
        config=config.artwork,
    )
    await state.artwork_worker.start()

    state.lyrics_worker = LyricsWorker(spotify_client=spotify_client)
    await state.lyrics_worker.start()

    state.rich_metadata_worker = MetadataWorker(
        spotify_client=spotify_client,
        plex_client=plex_client,
    )
    await state.rich_metadata_worker.start()

    state.scan_worker = ScanWorker(plex_client)

    state.sync_worker = SyncWorker(
        soulseek_client,
        metadata_worker=state.rich_metadata_worker,
        artwork_worker=state.artwork_worker,
        lyrics_worker=state.lyrics_worker,
        scan_worker=state.scan_worker,
    )
    await state.sync_worker.start()

    state.retry_scheduler = RetryScheduler(state.sync_worker)
    await state.retry_scheduler.start()

    state.matching_worker = MatchingWorker(matching_engine)
    await state.matching_worker.start()

    await state.scan_worker.start()

    state.playlist_worker = PlaylistSyncWorker(spotify_client)
    await state.playlist_worker.start()

    state.backfill_service = BackfillService(config.spotify, spotify_client)
    state.backfill_worker = BackfillWorker(state.backfill_service)
    await state.backfill_worker.start()

    interval_seconds = _resolve_watchlist_interval(os.getenv("WATCHLIST_INTERVAL"))
    state.watchlist_worker = WatchlistWorker(
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        sync_worker=state.sync_worker,
        interval_seconds=interval_seconds,
    )
    await state.watchlist_worker.start()

    state.metadata_worker = MetadataUpdateWorker(
        state.scan_worker,
        state.matching_worker,
    )

    def _load_preferences() -> dict[str, bool]:
        with session_scope() as session:
            records = session.execute(select(ArtistPreference)).scalars().all()
            return {record.release_id: record.selected for record in records if record.release_id}

    state.auto_sync_worker = AutoSyncWorker(
        spotify_client,
        plex_client,
        soulseek_client,
        beets_client,
        preferences_loader=_load_preferences,
    )
    await state.auto_sync_worker.start()

    state.discography_worker = DiscographyWorker(
        spotify_client,
        soulseek_client,
        plex_client=plex_client,
        beets_client=beets_client,
        artwork_worker=state.artwork_worker,
        lyrics_worker=state.lyrics_worker,
    )
    await state.discography_worker.start()


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
        "auto_sync_worker",
        "artwork_worker",
        "lyrics_worker",
        "rich_metadata_worker",
        "retry_scheduler",
        "sync_worker",
        "matching_worker",
        "scan_worker",
        "playlist_worker",
        "backfill_worker",
        "watchlist_worker",
        "metadata_worker",
        "discography_worker",
    ]:
        await _stop_worker(getattr(state, attribute, None))
        if hasattr(state, attribute):
            delattr(state, attribute)


async def _close_plex_client() -> None:
    try:
        plex_client = get_plex_client()
    except ValueError:
        return
    close_fn = getattr(plex_client, "close", None)
    if callable(close_fn):
        result = close_fn()
        if inspect.isawaitable(result):
            await result


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = get_app_config()
    _configure_application(config)

    if _should_start_workers():
        await _start_background_workers(app, config)
    else:
        logger.info("Background workers disabled via HARMONY_DISABLE_WORKERS")

    logger.info("Harmony application started")
    try:
        yield
    finally:
        await _stop_background_workers(app)
        await _close_plex_client()
        logger.info("Harmony application stopped")


app = FastAPI(title="Harmony Backend", version="1.4.0", lifespan=lifespan)

app.include_router(spotify_router, prefix="/spotify", tags=["Spotify"])
app.include_router(backfill_router, prefix="/spotify/backfill", tags=["Spotify Backfill"])
app.include_router(spotify_free_router)
app.include_router(free_ingest_router)
app.include_router(imports_router)
app.include_router(plex_router, prefix="/plex", tags=["Plex"])
app.include_router(soulseek_router, prefix="/soulseek", tags=["Soulseek"])
app.include_router(matching_router, prefix="/matching", tags=["Matching"])
app.include_router(settings_router, prefix="/settings", tags=["Settings"])
app.include_router(beets_router, prefix="/beets", tags=["Beets"])
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
