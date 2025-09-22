import os
import subprocess
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.config.settings import config_manager
from app.utils.logging_config import get_logger

logger = get_logger("beets_router")

router = APIRouter()


# ----------------------------
# Request / Response Schemas
# ----------------------------


class ImportRequest(BaseModel):
    path: str
    quiet: bool = True
    autotag: bool = True


class ImportResponse(BaseModel):
    success: bool
    message: str


class UpdateRequest(BaseModel):
    path: Optional[str] = None


class UpdateResponse(BaseModel):
    success: bool
    message: str


class ListAlbumsResponse(BaseModel):
    albums: List[str]


class ListTracksResponse(BaseModel):
    tracks: List[str]


# ----------------------------
# Helper functions
# ----------------------------


async def _run_beets_command(args: List[str]) -> str:
    """Execute a beets CLI command in a worker thread and return its output."""

    try:
        logger.info("Running beets command: beets %s", " ".join(args))
        result = await run_in_threadpool(
            subprocess.run,
            ["beet"] + args,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, **config_manager.get_beets_env()},
        )
        return (result.stdout or "").strip()
    except subprocess.CalledProcessError as exc:
        error_message = (exc.stderr or str(exc)).strip()
        logger.error("Beets command failed: %s", error_message)
        raise HTTPException(status_code=500, detail=f"Beets error: {error_message}") from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected error running beets: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ----------------------------
# Endpoints
# ----------------------------


@router.post("/import", response_model=ImportResponse)
async def import_music(req: ImportRequest) -> ImportResponse:
    """Import new music into the Beets library."""

    args = ["import"]
    if req.quiet:
        args.append("-q")
    if req.autotag:
        args.append("-A")
    args.append(req.path)

    output = await _run_beets_command(args)
    return ImportResponse(success=True, message=output or "Import completed")


@router.post("/update", response_model=UpdateResponse)
async def update_library(req: UpdateRequest) -> UpdateResponse:
    """Update Beets library metadata, optionally for a specific path."""

    args = ["update"]
    if req.path:
        args.append(req.path)

    output = await _run_beets_command(args)
    return UpdateResponse(success=True, message=output or "Library updated")


@router.get("/albums", response_model=ListAlbumsResponse)
async def list_albums() -> ListAlbumsResponse:
    """List all albums managed by Beets."""

    output = await _run_beets_command(["ls", "-a"])
    albums = [line for line in output.splitlines() if line]
    return ListAlbumsResponse(albums=albums)


@router.get("/tracks", response_model=ListTracksResponse)
async def list_tracks() -> ListTracksResponse:
    """List all track titles managed by Beets."""

    output = await _run_beets_command(["ls", "-f", "$title"])
    tracks = [line for line in output.splitlines() if line]
    return ListTracksResponse(tracks=tracks)


@router.get("/stats")
async def library_stats() -> dict:
    """Return statistics about the Beets library."""

    output = await _run_beets_command(["stats"])
    return {"stats": output}
