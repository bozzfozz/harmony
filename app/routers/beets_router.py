from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.core.beets_client import BeetsClient, BeetsClientError
from app.utils.logging_config import get_logger

logger = get_logger("beets_router")

router = APIRouter()
beets_client = BeetsClient()


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


class RemoveRequest(BaseModel):
    query: str
    force: bool = False


class RemoveResponse(BaseModel):
    success: bool
    removed: Optional[int] = None
    output: Optional[str] = None


class MoveRequest(BaseModel):
    query: Optional[str] = None


class MoveResponse(BaseModel):
    success: bool
    moved: Optional[int] = None
    output: Optional[str] = None


class WriteRequest(BaseModel):
    query: Optional[str] = None


class WriteResponse(BaseModel):
    success: bool
    written: Optional[int] = None
    output: Optional[str] = None


class ListAlbumsResponse(BaseModel):
    albums: List[str]


class ListTracksResponse(BaseModel):
    tracks: List[str]


class FieldsResponse(BaseModel):
    fields: List[str]


class QueryRequest(BaseModel):
    query: str
    format: str = "$artist - $album - $title"


class QueryResponse(BaseModel):
    results: List[str]


# ----------------------------
# Helper functions
# ----------------------------


async def _call_client(method, *args, **kwargs):
    try:
        return await run_in_threadpool(method, *args, **kwargs)
    except BeetsClientError as exc:
        detail = str(exc)
        if detail.startswith("Invalid query syntax"):
            logger.error("Invalid query syntax: %s", detail)
            raise HTTPException(status_code=400, detail="Invalid query syntax") from exc
        if detail == "Query must not be empty":
            logger.error("Empty query provided")
            raise HTTPException(status_code=400, detail=detail) from exc
        logger.error("Beets client error: %s", detail)
        raise HTTPException(status_code=500, detail=detail) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected error running beets: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ----------------------------
# Endpoints
# ----------------------------


@router.post("/import", response_model=ImportResponse)
async def import_music(req: ImportRequest) -> ImportResponse:
    """Import new music into the Beets library."""

    output = await _call_client(
        beets_client.import_file,
        req.path,
        quiet=req.quiet,
        autotag=req.autotag,
    )
    return ImportResponse(success=True, message=output or "Import completed")


@router.post("/update", response_model=UpdateResponse)
async def update_library(req: UpdateRequest) -> UpdateResponse:
    """Update Beets library metadata, optionally for a specific path."""

    output = await _call_client(beets_client.update, req.path)
    return UpdateResponse(success=True, message=output or "Library updated")


@router.post(
    "/remove", response_model=RemoveResponse, response_model_exclude_none=True
)
async def remove_items(req: RemoveRequest) -> RemoveResponse:
    """Remove library items that match a query."""

    result = await _call_client(beets_client.remove, req.query, force=req.force)
    return RemoveResponse(**result)


@router.post(
    "/move", response_model=MoveResponse, response_model_exclude_none=True
)
async def move_items(req: MoveRequest) -> MoveResponse:
    """Move files in the Beets library, optionally filtering by a query."""

    result = await _call_client(beets_client.move, req.query)
    return MoveResponse(**result)


@router.post(
    "/write", response_model=WriteResponse, response_model_exclude_none=True
)
async def write_tags(req: WriteRequest) -> WriteResponse:
    """Write tags to files, optionally filtering by a query."""

    result = await _call_client(beets_client.write, req.query)
    return WriteResponse(**result)


@router.get("/albums", response_model=ListAlbumsResponse)
async def list_albums() -> ListAlbumsResponse:
    """List all albums managed by Beets."""

    albums = await _call_client(beets_client.list_albums)
    return ListAlbumsResponse(albums=albums)


@router.get("/tracks", response_model=ListTracksResponse)
async def list_tracks() -> ListTracksResponse:
    """List all track titles managed by Beets."""

    tracks = await _call_client(beets_client.list_tracks)
    return ListTracksResponse(tracks=tracks)


@router.get("/stats")
async def library_stats() -> dict:
    """Return statistics about the Beets library."""

    stats = await _call_client(beets_client.stats)
    return {"stats": stats}


@router.get("/fields", response_model=FieldsResponse)
async def list_fields() -> FieldsResponse:
    """Return all available Beets fields."""

    fields = await _call_client(beets_client.fields)
    return FieldsResponse(fields=fields)


@router.post("/query", response_model=QueryResponse)
async def run_query(req: QueryRequest) -> QueryResponse:
    """Execute a formatted Beets query."""

    results = await _call_client(
        beets_client.query, req.query, fmt=req.format
    )
    return QueryResponse(results=results)
