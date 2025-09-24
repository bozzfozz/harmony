"""Routes that coordinate manual sync and aggregated search operations."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable

from fastapi import APIRouter, HTTPException, Request, status

from app import dependencies
from app.logging import get_logger
from app.utils.activity import record_activity
from app.workers import AutoSyncWorker, PlaylistSyncWorker, ScanWorker

router = APIRouter(prefix="/api", tags=["Sync"])
logger = get_logger(__name__)


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_manual_sync(request: Request) -> dict[str, Any]:
    """Run playlist and library synchronisation tasks on demand."""

    playlist_worker = _get_playlist_worker(request)
    scan_worker = _get_scan_worker(request)
    auto_worker = _get_auto_sync_worker(request)

    sources = ["spotify", "plex", "soulseek"]
    record_activity("sync", "sync_started", details={"mode": "manual", "sources": sources})

    results: Dict[str, str] = {}
    errors: Dict[str, str] = {}

    if playlist_worker is not None:
        try:
            await playlist_worker.sync_once()
            results["playlists"] = "completed"
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Playlist sync failed: %s", exc)
            errors["playlists"] = str(exc)
    else:
        errors["playlists"] = "Playlist worker unavailable"

    if scan_worker is not None:
        try:
            await scan_worker.run_once()
            results["library_scan"] = "completed"
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Library scan failed: %s", exc)
            errors["library_scan"] = str(exc)
    else:
        errors["library_scan"] = "Scan worker unavailable"

    if auto_worker is not None:
        try:
            await auto_worker.run_once(source="manual")
            results["auto_sync"] = "completed"
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Auto sync failed: %s", exc)
            errors["auto_sync"] = str(exc)
    else:
        errors["auto_sync"] = "AutoSync worker unavailable"

    response: Dict[str, Any] = {"message": "Sync triggered", "results": results}
    if errors:
        response["errors"] = errors

    counters = {
        "tracks_synced": 0,
        "tracks_skipped": 0,
        "errors": len(errors),
    }
    if errors:
        error_list = [
            {"source": key, "message": value}
            for key, value in sorted(errors.items())
        ]
        record_activity(
            "sync",
            "sync_partial",
            details={
                "mode": "manual",
                "sources": sources,
                "results": results,
                "errors": error_list,
            },
        )

    record_activity(
        "sync",
        "sync_completed",
        details={
            "mode": "manual",
            "sources": sources,
            "results": results,
            "counters": counters,
        },
    )
    return response


@router.post("/search")
async def global_search(request: Request, payload: Dict[str, Any]) -> dict[str, Any]:
    """Perform a combined search across Spotify, Plex and Soulseek."""

    query = str(payload.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query is required")

    requested_sources = _normalise_sources(payload.get("sources"))
    detail_sources = sorted(requested_sources)
    record_activity(
        "search",
        "search_started",
        details={"query": query, "sources": detail_sources},
    )
    results: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    if "spotify" in requested_sources:
        try:
            results["spotify"] = _search_spotify(dependencies.get_spotify_client(), query)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Spotify search failed: %s", exc)
            errors["spotify"] = str(exc)

    async_tasks: Dict[str, asyncio.Future[Any]] = {}
    if "plex" in requested_sources:
        plex_client = _ensure_plex_client()
        if plex_client is not None:
            async_tasks["plex"] = asyncio.create_task(_search_plex(plex_client, query))
        else:
            errors["plex"] = "Plex client unavailable"

    if "soulseek" in requested_sources:
        soulseek_client = _ensure_soulseek_client()
        if soulseek_client is not None:
            async_tasks["soulseek"] = asyncio.create_task(_search_soulseek(soulseek_client, query))
        else:
            errors["soulseek"] = "Soulseek client unavailable"

    if async_tasks:
        async_results = await asyncio.gather(*async_tasks.values(), return_exceptions=True)
        for source, value in zip(async_tasks.keys(), async_results):
            if isinstance(value, Exception):  # pragma: no cover - defensive logging
                logger.exception("%s search failed: %s", source.title(), value)
                errors[source] = str(value)
            else:
                results[source] = value

    response: Dict[str, Any] = {"query": query, "results": results}
    if errors:
        response["errors"] = errors

    summary = _summarise_search_results(results)
    record_activity(
        "search",
        "search_completed",
        details={
            "query": query,
            "sources": detail_sources,
            "matches": summary,
        },
    )

    if errors:
        error_list = [
            {"source": key, "message": value}
            for key, value in sorted(errors.items())
        ]
        record_activity(
            "search",
            "search_failed",
            details={
                "query": query,
                "sources": detail_sources,
                "errors": error_list,
            },
        )
    return response


def _get_playlist_worker(request: Request) -> PlaylistSyncWorker | None:
    worker = getattr(request.app.state, "playlist_worker", None)
    if isinstance(worker, PlaylistSyncWorker):
        return worker
    try:
        spotify_client = dependencies.get_spotify_client()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Unable to initialise Spotify client for playlist sync: %s", exc)
        return None
    worker = PlaylistSyncWorker(spotify_client, interval_seconds=900.0)
    request.app.state.playlist_worker = worker
    return worker


def _get_scan_worker(request: Request) -> ScanWorker | None:
    worker = getattr(request.app.state, "scan_worker", None)
    if isinstance(worker, ScanWorker):
        return worker
    try:
        plex_client = dependencies.get_plex_client()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Unable to initialise Plex client for scan: %s", exc)
        return None
    worker = ScanWorker(plex_client)
    request.app.state.scan_worker = worker
    return worker


def _get_auto_sync_worker(request: Request) -> AutoSyncWorker | None:
    worker = getattr(request.app.state, "auto_sync_worker", None)
    if isinstance(worker, AutoSyncWorker):
        return worker
    try:
        spotify_client = dependencies.get_spotify_client()
        plex_client = dependencies.get_plex_client()
        soulseek_client = dependencies.get_soulseek_client()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Unable to initialise clients for auto sync: %s", exc)
        return None
    try:
        from app.core.beets_client import BeetsClient  # local import to avoid heavy startup

        beets_client = BeetsClient()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Unable to initialise Beets client for auto sync: %s", exc)
        return None
    worker = AutoSyncWorker(spotify_client, plex_client, soulseek_client, beets_client)
    request.app.state.auto_sync_worker = worker
    return worker


def _search_spotify(client, query: str) -> Dict[str, Any]:
    tracks = client.search_tracks(query).get("tracks", {}).get("items", [])
    artists = client.search_artists(query).get("artists", {}).get("items", [])
    albums = client.search_albums(query).get("albums", {}).get("items", [])
    return {"tracks": tracks, "artists": artists, "albums": albums}


async def _search_soulseek(client, query: str) -> Dict[str, Any]:
    response = await client.search(query)
    if isinstance(response, dict):
        return response
    if isinstance(response, Iterable):
        return {"results": list(response)}
    return {"results": [response] if response else []}


async def _search_plex(client, query: str) -> list[Dict[str, Any]]:
    try:
        libraries = await client.get_libraries()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to load Plex libraries: %s", exc)
        return []

    sections = (libraries or {}).get("MediaContainer", {}).get("Directory", [])
    query_lower = query.lower()
    matches: list[Dict[str, Any]] = []

    for section in sections or []:
        section_id = section.get("key")
        if not section_id:
            continue
        try:
            items = await client.get_library_items(section_id, params={"type": "10"})
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Failed to query Plex section %s: %s", section_id, exc)
            continue
        metadata = (items or {}).get("MediaContainer", {}).get("Metadata", []) or []
        for entry in metadata:
            title = str(entry.get("title") or "")
            parent = str(entry.get("parentTitle") or "")
            rating_key = entry.get("ratingKey")
            if title or parent:
                haystack = f"{title} {parent}".lower()
                if query_lower not in haystack:
                    continue
            matches.append(
                {
                    "id": rating_key,
                    "title": title or str(rating_key),
                    "parentTitle": parent,
                    "source": "plex",
                }
            )
    return matches


def _summarise_search_results(results: Dict[str, Any]) -> Dict[str, int]:
    summary: Dict[str, int] = {}
    for source, payload in results.items():
        summary[source] = _count_matches_for_source(source, payload)
    return summary


def _count_matches_for_source(source: str, payload: Any) -> int:
    if payload is None:
        return 0
    if source == "spotify" and isinstance(payload, dict):
        total = 0
        for key in ("tracks", "artists", "albums"):
            value = payload.get(key)
            if isinstance(value, list):
                total += len(value)
            elif isinstance(value, dict):
                items = value.get("items")
                if isinstance(items, list):
                    total += len(items)
        return total
    if source == "plex":
        if isinstance(payload, list):
            return len(payload)
        return 0
    if source == "soulseek" and isinstance(payload, dict):
        results_list = payload.get("results")
        if isinstance(results_list, list):
            return len(results_list)
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return len(payload)
    return 0


def _ensure_plex_client():
    try:
        return dependencies.get_plex_client()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Unable to access Plex client: %s", exc)
        return None


def _ensure_soulseek_client():
    try:
        return dependencies.get_soulseek_client()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Unable to access Soulseek client: %s", exc)
        return None


def _normalise_sources(sources: Any) -> set[str]:
    if not sources:
        return {"spotify", "plex", "soulseek"}
    if isinstance(sources, str):
        return {sources.lower()}
    if isinstance(sources, Iterable):
        return {str(item).lower() for item in sources}
    return {"spotify", "plex", "soulseek"}

