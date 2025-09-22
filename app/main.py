"""Entry point for the Harmony FastAPI application."""
from __future__ import annotations

import os

from fastapi import FastAPI

from app.dependencies import (
    get_app_config,
    get_matching_engine,
    get_plex_client,
    get_soulseek_client,
    get_spotify_client,
)
from app.db import init_db
from app.logging import configure_logging, get_logger
from app.routers import matching_router, plex_router, settings_router, soulseek_router, spotify_router
from app.workers import MatchingWorker, PlaylistSyncWorker, ScanWorker, SyncWorker

app = FastAPI(title="Harmony Backend", version="1.3.0")
logger = get_logger(__name__)

app.include_router(spotify_router, prefix="/spotify", tags=["Spotify"])
app.include_router(plex_router, prefix="/plex", tags=["Plex"])
app.include_router(soulseek_router, prefix="/soulseek", tags=["Soulseek"])
app.include_router(matching_router, prefix="/matching", tags=["Matching"])
app.include_router(settings_router, prefix="/settings", tags=["Settings"])


@app.on_event("startup")
async def startup_event() -> None:
    config = get_app_config()
    configure_logging(config.logging.level)
    init_db()
    logger.info("Database initialised")

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

    logger.info("Harmony application started")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if worker := getattr(app.state, "sync_worker", None):
        await worker.stop()
    if worker := getattr(app.state, "matching_worker", None):
        await worker.stop()
    if worker := getattr(app.state, "scan_worker", None):
        await worker.stop()
    if worker := getattr(app.state, "playlist_worker", None):
        await worker.stop()
    logger.info("Harmony application stopped")


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "version": app.version}
