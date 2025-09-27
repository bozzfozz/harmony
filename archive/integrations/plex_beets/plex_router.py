"""Lean Plex API router focused on matching and library scans."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, TYPE_CHECKING, cast

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.plex_client import (
    PlexClient,
    PlexClientAuthError,
    PlexClientError,
    PlexClientNotFoundError,
    PlexClientRateLimitedError,
)
from app.dependencies import get_plex_client
from app.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from app.workers.scan_worker import ScanWorker


logger = get_logger(__name__)

router = APIRouter()

SUPPORTED_SEARCH_TYPES: set[str] = {"artist", "album", "track"}


def _error_response(*, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": {"code": code, "message": message}},
    )


def _map_client_error(exc: PlexClientError) -> JSONResponse:
    if isinstance(exc, PlexClientAuthError):
        status_code = (
            status.HTTP_401_UNAUTHORIZED
            if exc.status_code == status.HTTP_401_UNAUTHORIZED
            else status.HTTP_403_FORBIDDEN
        )
        return _error_response(
            status_code=status_code,
            code="AUTH_ERROR",
            message="Authentication with Plex failed",
        )
    if isinstance(exc, PlexClientNotFoundError):
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="Requested Plex resource was not found",
        )
    if isinstance(exc, PlexClientRateLimitedError):
        return _error_response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="RATE_LIMITED",
            message=str(exc),
        )
    return _error_response(
        status_code=status.HTTP_502_BAD_GATEWAY,
        code="DEPENDENCY_ERROR",
        message=str(exc),
    )


def _resolve_scan_worker(request: Request) -> Optional["ScanWorker"]:
    worker = getattr(request.app.state, "scan_worker", None)
    if worker is None or not hasattr(worker, "request_scan"):
        return None
    if TYPE_CHECKING:  # pragma: no cover - not executed at runtime
        assert isinstance(worker, ScanWorker)
    return cast("ScanWorker", worker)


@router.get("/status")
async def plex_status(client: PlexClient = Depends(get_plex_client)) -> Any:
    try:
        status_payload = await client.get_status()
    except PlexClientError as exc:
        logger.warning("Plex status query failed: %s", exc)
        return _map_client_error(exc)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Unexpected Plex status failure: %s", exc)
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="DEPENDENCY_ERROR",
            message="Unable to query Plex status",
        )

    server_info = status_payload.get("server", {}) if isinstance(status_payload, dict) else {}
    libraries = status_payload.get("libraries", 0) if isinstance(status_payload, dict) else 0
    return {
        "ok": True,
        "server": {
            "name": str(server_info.get("name", "unknown")),
            "version": str(server_info.get("version", "")),
        },
        "libraries": int(libraries or 0),
    }


@router.get("/libraries")
async def plex_libraries(client: PlexClient = Depends(get_plex_client)) -> Any:
    try:
        payload = await client.get_libraries()
    except PlexClientError as exc:
        logger.warning("Listing Plex libraries failed: %s", exc)
        return _map_client_error(exc)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Unexpected Plex library failure: %s", exc)
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="DEPENDENCY_ERROR",
            message="Unable to list Plex libraries",
        )

    directories: Iterable[Dict[str, Any]] = []
    if isinstance(payload, dict):
        container = payload.get("MediaContainer")
        if isinstance(container, dict):
            directory_field = container.get("Directory")
            if isinstance(directory_field, list):
                directories = [entry for entry in directory_field if isinstance(entry, dict)]

    simplified: List[Dict[str, Any]] = []
    for entry in directories:
        section_id = entry.get("key")
        title = entry.get("title")
        section_type = entry.get("type") or entry.get("agent")
        if section_id is None or title is None:
            continue
        simplified.append(
            {
                "section_id": str(section_id),
                "title": str(title),
                "type": str(section_type or "unknown"),
            }
        )

    return {"ok": True, "data": simplified}


@router.post("/library/{section_id}/scan", status_code=status.HTTP_202_ACCEPTED)
async def plex_trigger_scan(
    section_id: str,
    request: Request,
    client: PlexClient = Depends(get_plex_client),
) -> Any:
    worker = _resolve_scan_worker(request)
    try:
        if worker is not None:
            queued = await worker.request_scan(section_id)
        else:
            await client.refresh_library_section(section_id, full=False)
            queued = True
    except PlexClientError as exc:
        logger.warning("Failed to trigger Plex scan for section %s: %s", section_id, exc)
        return _map_client_error(exc)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Unexpected Plex scan error for section %s: %s", section_id, exc)
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="DEPENDENCY_ERROR",
            message="Unable to trigger Plex scan",
        )

    return {"ok": True, "queued": bool(queued), "section_id": section_id}


@router.get("/search")
async def plex_search(
    q: str = Query(..., min_length=1, max_length=200),
    type: Optional[str] = Query(None, alias="type"),
    client: PlexClient = Depends(get_plex_client),
) -> Any:
    item_type: Optional[str] = None
    if type is not None:
        candidate = type.strip().lower()
        if candidate not in SUPPORTED_SEARCH_TYPES:
            return _error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="VALIDATION_ERROR",
                message="Unsupported search type",
            )
        item_type = candidate

    mediatypes: Optional[Iterable[str]] = (item_type,) if item_type else None
    try:
        entries = await client.search_music(q, mediatypes=mediatypes, limit=50)
    except PlexClientError as exc:
        logger.warning("Plex search failed for query %s: %s", q, exc)
        return _map_client_error(exc)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Unexpected Plex search error for query %s: %s", q, exc)
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="DEPENDENCY_ERROR",
            message="Unable to query Plex search",
        )

    items: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalised = client.normalise_music_entry(entry)
        normalised_type = normalised.get("type") or entry.get("type")
        if normalised_type not in SUPPORTED_SEARCH_TYPES:
            continue
        section_id = entry.get("librarySectionID") or normalised.get("extra", {}).get(
            "librarySectionID"
        )
        guid_value = entry.get("guid")
        if not guid_value:
            guid_container = entry.get("Guid")
            if isinstance(guid_container, list) and guid_container:
                first_guid = guid_container[0]
                if isinstance(first_guid, dict):
                    guid_value = first_guid.get("id")
        if not guid_value:
            guid_value = normalised.get("extra", {}).get("guid")

        item = {
            "type": str(normalised_type),
            "title": str(normalised.get("title") or entry.get("title") or ""),
            "guid": str(guid_value or ""),
            "ratingKey": str(
                entry.get("ratingKey") or normalised.get("extra", {}).get("ratingKey", "")
            ),
            "section_id": (
                int(section_id)
                if isinstance(section_id, (int, float))
                else str(section_id) if section_id else None
            ),
        }
        parent_title = entry.get("parentTitle") or normalised.get("album")
        grandparent_title = entry.get("grandparentTitle")
        if normalised_type == "album":
            item["parentTitle"] = str(parent_title or "")
        if normalised_type == "track":
            item["parentTitle"] = str(parent_title or "")
            item["grandparentTitle"] = str(
                grandparent_title or normalised.get("artists", [""])[0] or ""
            )
        items.append(item)

    return {"ok": True, "data": items}


@router.get("/tracks")
async def plex_tracks(
    artist: Optional[str] = Query(None, min_length=1, max_length=200),
    album: Optional[str] = Query(None, min_length=1, max_length=200),
    client: PlexClient = Depends(get_plex_client),
) -> Any:
    if not artist and not album:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message="artist or album parameter required",
        )

    try:
        tracks = await client.list_tracks(artist=artist, album=album)
    except PlexClientError as exc:
        logger.warning("Listing Plex tracks failed: %s", exc)
        return _map_client_error(exc)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Unexpected Plex track lookup failure: %s", exc)
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="DEPENDENCY_ERROR",
            message="Unable to list Plex tracks",
        )

    compact: List[Dict[str, Any]] = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        title = track.get("title")
        rating_key = track.get("ratingKey")
        if not title or not rating_key:
            continue
        compact.append(
            {
                "title": str(title),
                "track": int(track.get("track", 0) or 0),
                "guid": str(track.get("guid", "")),
                "ratingKey": str(rating_key),
                "section_id": track.get("section_id"),
            }
        )

    return {"ok": True, "data": compact}
