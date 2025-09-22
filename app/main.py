from fastapi import FastAPI

from app.routers import (
    beets_router,
    matching_router,
    plex_router,
    settings_router,
    soulseek_router,
    spotify_router,
    sync_router,
)
from app.utils.logging_config import get_logger
from app.db import init_db

logger = get_logger("main")

app = FastAPI(title="Harmony Backend", version="1.0.0")

# Routers
app.include_router(soulseek_router.router, prefix="/soulseek", tags=["Soulseek"])
app.include_router(beets_router.router, prefix="/beets", tags=["Beets"])
app.include_router(matching_router.router, prefix="/matching", tags=["Matching"])
app.include_router(settings_router.router, prefix="/settings", tags=["Settings"])
app.include_router(spotify_router.router, prefix="/spotify", tags=["Spotify"])
app.include_router(plex_router.router, prefix="/plex", tags=["Plex"])
app.include_router(sync_router.router)


@app.on_event("startup")
def startup() -> None:
    init_db()
    logger.info("Application started successfully")


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "message": "Harmony backend running"}
