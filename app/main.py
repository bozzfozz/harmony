"""Entry point for the Harmony FastAPI application."""
from __future__ import annotations

import os

import inspect

from fastapi import FastAPI

from app.core.config import DEFAULT_SETTINGS
from app.core.beets_client import BeetsClient
from app.dependencies import (
    get_app_config,
    get_matching_engine,
    get_plex_client,
    get_soulseek_client,
    get_spotify_client,
)
from app.db import init_db, session_scope
from app.logging import configure_logging, get_logger
from app.routers import (
    activity_router,
    beets_router,
    download_router,
    matching_router,
    metadata_router,
    plex_router,
    settings_router,
    sync_router,
    system_router,
    soulseek_router,
    spotify_router,
)
from app.utils.activity import activity_manager
from app.utils.settings_store import ensure_default_settings
from app.workers import (
    AutoSyncWorker,
    MatchingWorker,
    MetadataUpdateWorker,
    PlaylistSyncWorker,
    ScanWorker,
    SyncWorker,
)
from app.models import ArtistPreference
from sqlalchemy import select

app = FastAPI(title="Harmony Backend", version="1.4.0")
logger = get_logger(__name__)

app.include_router(spotify_router, prefix="/spotify", tags=["Spotify"])
app.include_router(plex_router, prefix="/plex", tags=["Plex"])
app.include_router(soulseek_router, prefix="/soulseek", tags=["Soulseek"])
app.include_router(matching_router, prefix="/matching", tags=["Matching"])
app.include_router(settings_router, prefix="/settings", tags=["Settings"])
app.include_router(beets_router, prefix="/beets", tags=["Beets"])
app.include_router(metadata_router, tags=["Metadata"])
app.include_router(sync_router, tags=["Sync"])
app.include_router(system_router, tags=["System"])
app.include_router(download_router)
app.include_router(activity_router)


@app.on_event("startup")
async def startup_event() -> None:
    config = get_app_config()
    configure_logging(config.logging.level)
    init_db()
    ensure_default_settings(DEFAULT_SETTINGS)
    logger.info("Database initialised")
    activity_manager.refresh_cache()

    if os.getenv("HARMONY_DISABLE_WORKERS") not in {"1", "true", "TRUE"}:
        soulseek_client = get_soulseek_client()
        matching_engine = get_matching_engine()
        plex_client = get_plex_client()
        spotify_client = get_spotify_client()

        app.state.sync_worker = SyncWorker(soulseek_client)
        await app.state.sync_worker.start()

        app.state.matching_worker = MatchingWorker(matching_engine)
        await app.state.matching_worker.start()

        app.state.scan_worker = ScanWorker(plex_client)
        await app.state.scan_worker.start()

        app.state.playlist_worker = PlaylistSyncWorker(spotify_client)
        await app.state.playlist_worker.start()

        app.state.metadata_worker = MetadataUpdateWorker(
            app.state.scan_worker,
            app.state.matching_worker,
        )

        beets_client = BeetsClient()
        def _load_preferences() -> dict[str, bool]:
            with session_scope() as session:
                records = (
                    session.execute(select(ArtistPreference)).scalars().all()
                )
                return {
                    record.release_id: record.selected
                    for record in records
                    if record.release_id
                }

        app.state.auto_sync_worker = AutoSyncWorker(
            spotify_client,
            plex_client,
            soulseek_client,
            beets_client,
            preferences_loader=_load_preferences,
        )
        await app.state.auto_sync_worker.start()

    logger.info("Harmony application started")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if worker := getattr(app.state, "auto_sync_worker", None):
        await worker.stop()
    if worker := getattr(app.state, "sync_worker", None):
        await worker.stop()
    if worker := getattr(app.state, "matching_worker", None):
        await worker.stop()
    if worker := getattr(app.state, "scan_worker", None):
        await worker.stop()
    if worker := getattr(app.state, "playlist_worker", None):
        await worker.stop()
    if worker := getattr(app.state, "metadata_worker", None):
        await worker.stop()
    try:
        plex_client = get_plex_client()
    except ValueError:
        plex_client = None
    close_fn = getattr(plex_client, "close", None)
    if callable(close_fn):
        result = close_fn()
        if inspect.isawaitable(result):
            await result
    logger.info("Harmony application stopped")


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "version": app.version}
