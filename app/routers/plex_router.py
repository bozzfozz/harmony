"""Extended Plex API endpoints exposed through FastAPI."""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.plex_client import PlexClient, PlexClientError
from app.dependencies import get_plex_client
from app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _collect_query_params(request: Request) -> Dict[str, Any]:
    return {key: value for key, value in request.query_params.multi_items()}


@router.get("/status")
async def plex_status(client: PlexClient = Depends(get_plex_client)) -> Dict[str, Any]:
    try:
        sessions = await client.get_sessions()
        stats = await client.get_library_statistics()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to query Plex status: %s", exc)
        return {"status": "disconnected"}
    return {"status": "connected", "sessions": sessions, "library": stats}


@router.get("/library/sections")
async def list_libraries(
    request: Request, client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    try:
        params = _collect_query_params(request)
        return await client.get_libraries(params=params or None)
    except PlexClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/libraries", include_in_schema=False)
async def list_libraries_legacy(
    request: Request, client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    """Backward compatible alias for :func:`list_libraries`."""

    return await list_libraries(request, client)


@router.get("/library/sections/{section_id}/all")
async def browse_library(
    section_id: str, request: Request, client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    try:
        params = _collect_query_params(request)
        return await client.get_library_items(section_id, params=params or None)
    except PlexClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/library/{section_id}/items", include_in_schema=False)
async def browse_library_legacy(
    section_id: str, request: Request, client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    """Backward compatible alias for :func:`browse_library`."""

    return await browse_library(section_id, request, client)


@router.get("/library/metadata/{item_id}")
async def fetch_metadata(item_id: str, client: PlexClient = Depends(get_plex_client)) -> Dict[str, Any]:
    try:
        return await client.get_metadata(item_id)
    except PlexClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/metadata/{item_id}", include_in_schema=False)
async def fetch_metadata_legacy(
    item_id: str, client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    """Backward compatible alias for :func:`fetch_metadata`."""

    return await fetch_metadata(item_id, client)


@router.get("/status/sessions")
async def active_sessions(client: PlexClient = Depends(get_plex_client)) -> Dict[str, Any]:
    return await client.get_sessions()


@router.get("/sessions", include_in_schema=False)
async def active_sessions_legacy(client: PlexClient = Depends(get_plex_client)) -> Dict[str, Any]:
    """Backward compatible alias for :func:`active_sessions`."""

    return await active_sessions(client)


@router.get("/status/sessions/history/all")
async def session_history(
    request: Request, client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    params = _collect_query_params(request)
    return await client.get_session_history(params=params or None)


@router.get("/history", include_in_schema=False)
async def session_history_legacy(
    request: Request, client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    """Backward compatible alias for :func:`session_history`."""

    return await session_history(request, client)


@router.get("/timeline")
async def get_timeline(
    request: Request, client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    params = _collect_query_params(request)
    return await client.get_timeline(params=params or None)


@router.post("/timeline")
async def post_timeline(payload: Dict[str, Any], client: PlexClient = Depends(get_plex_client)) -> str:
    return await client.update_timeline(payload)


@router.post("/scrobble")
async def post_scrobble(payload: Dict[str, Any], client: PlexClient = Depends(get_plex_client)) -> str:
    return await client.scrobble(payload)


@router.post("/unscrobble")
async def post_unscrobble(payload: Dict[str, Any], client: PlexClient = Depends(get_plex_client)) -> str:
    return await client.unscrobble(payload)


@router.get("/playlists")
async def list_playlists(client: PlexClient = Depends(get_plex_client)) -> Dict[str, Any]:
    return await client.get_playlists()


@router.post("/playlists")
async def create_playlist(
    payload: Dict[str, Any], client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    return await client.create_playlist(payload)


@router.put("/playlists/{playlist_id}")
async def update_playlist(
    playlist_id: str, payload: Dict[str, Any], client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    return await client.update_playlist(playlist_id, payload)


@router.delete("/playlists/{playlist_id}")
async def delete_playlist(playlist_id: str, client: PlexClient = Depends(get_plex_client)) -> Dict[str, Any]:
    return await client.delete_playlist(playlist_id)


@router.post("/playQueues")
async def create_playqueue(
    payload: Dict[str, Any], client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    return await client.create_playqueue(payload)


@router.get("/playQueues/{playqueue_id}")
async def get_playqueue(playqueue_id: str, client: PlexClient = Depends(get_plex_client)) -> Dict[str, Any]:
    return await client.get_playqueue(playqueue_id)


@router.post("/rate")
async def rate_item(payload: Dict[str, Any], client: PlexClient = Depends(get_plex_client)) -> str:
    item_id = payload.get("key")
    rating = payload.get("rating")
    if not item_id or rating is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both 'key' and 'rating' must be provided",
        )
    return await client.rate_item(str(item_id), int(rating))


@router.post("/rate/{item_id}", include_in_schema=False)
async def rate_item_legacy(
    item_id: str, rating: int, client: PlexClient = Depends(get_plex_client)
) -> str:
    """Backward compatible alias for :func:`rate_item`."""

    return await client.rate_item(item_id, rating)


@router.post("/tags/{item_id}")
async def sync_tags(
    item_id: str, payload: Dict[str, Any], client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    tags = {key: value for key, value in payload.items() if isinstance(value, list)}
    return await client.sync_tags(item_id, tags)


@router.get("/devices")
async def list_devices(client: PlexClient = Depends(get_plex_client)) -> Dict[str, Any]:
    return await client.get_devices()


@router.get("/dvr")
async def list_dvr(client: PlexClient = Depends(get_plex_client)) -> Dict[str, Any]:
    return await client.get_dvr()


@router.get("/livetv")
async def list_live_tv(
    request: Request, client: PlexClient = Depends(get_plex_client)
) -> Dict[str, Any]:
    params = _collect_query_params(request)
    return await client.get_live_tv(params=params or None)


@router.get("/notifications")
async def listen_notifications(client: PlexClient = Depends(get_plex_client)) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async with client.listen_notifications() as websocket:
                async for message in websocket:
                    if message.type.name == "TEXT":
                        yield f"data: {message.data}\n\n".encode("utf-8")
                    elif message.type.name == "ERROR":
                        logger.error("Plex notification stream error: %s", websocket.exception())
                        break
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to stream Plex notifications: %s", exc)
            yield f"event: error\ndata: {exc}\n\n".encode("utf-8")

    return StreamingResponse(event_stream(), media_type="text/event-stream")

