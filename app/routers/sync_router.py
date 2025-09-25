"""Routes that coordinate manual sync and aggregated search operations."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app import dependencies
from app.db import session_scope
from app.logging import get_logger
from app.utils.activity import record_activity
from app.utils.events import SYNC_BLOCKED
from app.utils.service_health import collect_missing_credentials
from app.workers import AutoSyncWorker, PlaylistSyncWorker, ScanWorker

router = APIRouter(prefix="/api", tags=["Sync"])
logger = get_logger(__name__)


REQUIRED_SERVICES: tuple[str, ...] = ("spotify", "plex", "soulseek")


@dataclass(frozen=True)
class SearchFilters:
    """Filters that can be applied to aggregated search requests."""

    genre: str | None = None
    year: int | None = None
    quality: str | None = None


class SearchFilterPayload(BaseModel):
    """Payload model for optional search filters."""

    genre: str | None = Field(default=None, description="Optionales Genre-Filter")
    year: int | None = Field(default=None, ge=0, description="Optionales Jahr-Filter")
    quality: str | None = Field(
        default=None,
        description="Optionale Qualitätsanforderung (z. B. FLAC, 320kbps)",
    )

    @field_validator("genre", "quality", mode="before")
    @classmethod
    def _normalise_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    @field_validator("year", mode="before")
    @classmethod
    def _coerce_year(cls, value: Any) -> int | None:
        if value in {None, ""}:
            return None
        if isinstance(value, int):
            if value < 0:
                raise ValueError("year must be positive")
            return value
        if isinstance(value, float):
            if value < 0:
                raise ValueError("year must be positive")
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if not stripped.isdigit():
                raise ValueError("year must be a number")
            return int(stripped)
        raise ValueError("year must be numeric")

    def to_filters(self) -> SearchFilters:
        return SearchFilters(genre=self.genre, year=self.year, quality=self.quality)

    def as_activity_details(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class SearchRequest(BaseModel):
    """Request payload for the global search endpoint."""

    query: str = Field(..., description="Freitext-Suchbegriff")
    sources: List[str] | str | None = Field(
        default=None, description="Optionale Quellenauswahl (spotify, plex, soulseek)"
    )
    filters: SearchFilterPayload | None = Field(
        default=None, description="Optionale Filter für Genre, Jahr und Qualität"
    )

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Query is required")
        return stripped


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_manual_sync(request: Request) -> dict[str, Any]:
    """Run playlist and library synchronisation tasks on demand."""

    missing = _missing_credentials()
    if missing:
        missing_payload = {service: list(values) for service, values in missing.items()}
        logger.warning("Manual sync blocked due to missing credentials: %s", missing_payload)
        record_activity(
            "sync",
            SYNC_BLOCKED,
            details={"missing": missing_payload},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Sync blocked", "missing": missing_payload},
        )

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
async def global_search(request: Request, payload: SearchRequest) -> dict[str, Any]:
    """Perform a combined search across Spotify, Plex and Soulseek."""

    query = payload.query
    filter_payload = payload.filters or SearchFilterPayload()
    filters = filter_payload.to_filters()
    requested_sources = _normalise_sources(payload.sources)
    detail_sources = sorted(requested_sources)

    activity_details: Dict[str, Any] = {
        "query": query,
        "sources": detail_sources,
    }
    filter_details = filter_payload.as_activity_details()
    if filter_details:
        activity_details["filters"] = filter_details
        logger.info("Applying search filters: %s", filter_details)

    record_activity("search", "search_started", details=activity_details)

    results: Dict[str, List[Dict[str, Any]]] = {}
    errors: Dict[str, str] = {}

    if "spotify" in requested_sources:
        try:
            spotify_results = _search_spotify(
                dependencies.get_spotify_client(), query, filters
            )
            results["spotify"] = spotify_results
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Spotify search failed: %s", exc)
            errors["spotify"] = str(exc)
            results["spotify"] = []

    async_tasks: Dict[str, asyncio.Future[List[Dict[str, Any]]]] = {}
    if "plex" in requested_sources:
        plex_client = _ensure_plex_client()
        if plex_client is not None:
            async_tasks["plex"] = asyncio.create_task(
                _search_plex(plex_client, query, filters)
            )
        else:
            errors["plex"] = "Plex client unavailable"
            results["plex"] = []

    if "soulseek" in requested_sources:
        soulseek_client = _ensure_soulseek_client()
        if soulseek_client is not None:
            async_tasks["soulseek"] = asyncio.create_task(
                _search_soulseek(soulseek_client, query, filters)
            )
        else:
            errors["soulseek"] = "Soulseek client unavailable"
            results["soulseek"] = []

    if async_tasks:
        async_results = await asyncio.gather(*async_tasks.values(), return_exceptions=True)
        for source, value in zip(async_tasks.keys(), async_results):
            if isinstance(value, Exception):  # pragma: no cover - defensive logging
                logger.exception("%s search failed: %s", source.title(), value)
                errors[source] = str(value)
                results[source] = []
            else:
                results[source] = value

    for source in requested_sources:
        results.setdefault(source, [])

    combined_results: List[Dict[str, Any]] = []
    for source in detail_sources:
        combined_results.extend(results.get(source, []))

    response: Dict[str, Any] = {"query": query, "results": combined_results}
    if filter_details:
        response["filters"] = filter_details
    if errors:
        response["errors"] = errors

    summary = _summarise_search_results(results)
    summary_details = dict(activity_details)
    summary_details["matches"] = summary
    record_activity("search", "search_completed", details=summary_details)

    if errors:
        error_list = [
            {"source": key, "message": value}
            for key, value in sorted(errors.items())
        ]
        failure_details = dict(activity_details)
        failure_details["errors"] = error_list
        record_activity("search", "search_failed", details=failure_details)
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


def _search_spotify(
    client,
    query: str,
    filters: SearchFilters,
) -> List[Dict[str, Any]]:
    if filters.quality:
        # Spotify streams have no controllable download quality – skip when explicit
        # lossless/bitrate filters are requested.
        return []

    results: List[Dict[str, Any]] = []

    tracks = (
        client.search_tracks(query, genre=filters.genre, year=filters.year)
        .get("tracks", {})
        .get("items", [])
    )
    for item in tracks or []:
        normalised = _normalise_spotify_track(item)
        if normalised is None:
            continue
        if filters.year and normalised.get("year") not in {None, filters.year}:
            continue
        if filters.genre and not _genre_matches(normalised.get("genre"), filters.genre):
            continue
        results.append(normalised)

    albums = (
        client.search_albums(query, genre=filters.genre, year=filters.year)
        .get("albums", {})
        .get("items", [])
    )
    for item in albums or []:
        normalised = _normalise_spotify_album(item)
        if normalised is None:
            continue
        if filters.year and normalised.get("year") not in {None, filters.year}:
            continue
        if filters.genre and not _genre_matches(normalised.get("genre"), filters.genre):
            continue
        results.append(normalised)

    artists = (
        client.search_artists(query, genre=filters.genre, year=filters.year)
        .get("artists", {})
        .get("items", [])
    )
    for item in artists or []:
        normalised = _normalise_spotify_artist(item)
        if normalised is not None:
            if filters.genre and not _genre_matches(normalised.get("genre"), filters.genre):
                continue
            results.append(normalised)

    return results


async def _search_soulseek(
    client,
    query: str,
    filters: SearchFilters,
) -> List[Dict[str, Any]]:
    response = await client.search(query)
    return _normalise_soulseek_results(response, filters)


async def _search_plex(
    client,
    query: str,
    filters: SearchFilters,
) -> list[Dict[str, Any]]:
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
            params = {"type": "10"}
            if filters.year is not None:
                params["year"] = filters.year
            if filters.genre is not None:
                params["genre"] = filters.genre
            items = await client.get_library_items(section_id, params=params)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Failed to query Plex section %s: %s", section_id, exc)
            continue
        metadata = (items or {}).get("MediaContainer", {}).get("Metadata", []) or []
        for entry in metadata:
            normalised = _normalise_plex_entry(entry, query_lower, filters)
            if normalised is None:
                continue
            matches.append(normalised)
    return matches


def _summarise_search_results(results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
    return {source: len(items) for source, items in results.items()}


def _normalise_spotify_track(item: Dict[str, Any]) -> Dict[str, Any] | None:
    track_id = item.get("id") or item.get("uri")
    title = str(item.get("name") or "").strip()
    album_payload = item.get("album") or {}
    album_name = str(album_payload.get("name") or "").strip()
    artist_names = [
        str(artist.get("name") or "").strip()
        for artist in item.get("artists", [])
        if isinstance(artist, dict) and artist.get("name")
    ]
    if not track_id or not title:
        return None
    genre = _extract_spotify_genre(item)
    if genre is None:
        genre = _extract_spotify_genre(album_payload)
    if genre is None:
        for artist_payload in item.get("artists", []) or []:
            genre = _extract_spotify_genre(artist_payload)
            if genre:
                break
    return {
        "id": str(track_id),
        "source": "spotify",
        "type": "track",
        "artist": ", ".join(filter(None, artist_names)) or None,
        "album": album_name or None,
        "title": title,
        "year": _parse_year(album_payload.get("release_date")),
        "genre": genre,
        "quality": None,
    }


def _normalise_spotify_album(item: Dict[str, Any]) -> Dict[str, Any] | None:
    album_id = item.get("id") or item.get("uri")
    name = str(item.get("name") or "").strip()
    artist_names = [
        str(artist.get("name") or "").strip()
        for artist in item.get("artists", [])
        if isinstance(artist, dict) and artist.get("name")
    ]
    if not album_id or not name:
        return None
    genre = _extract_spotify_genre(item)
    if genre is None:
        for artist_payload in item.get("artists", []) or []:
            genre = _extract_spotify_genre(artist_payload)
            if genre:
                break
    return {
        "id": str(album_id),
        "source": "spotify",
        "type": "album",
        "artist": ", ".join(filter(None, artist_names)) or None,
        "album": name,
        "title": name,
        "year": _parse_year(item.get("release_date")),
        "genre": genre,
        "quality": None,
    }


def _normalise_spotify_artist(item: Dict[str, Any]) -> Dict[str, Any] | None:
    artist_id = item.get("id") or item.get("uri")
    name = str(item.get("name") or "").strip()
    if not artist_id or not name:
        return None
    return {
        "id": str(artist_id),
        "source": "spotify",
        "type": "artist",
        "artist": name,
        "album": None,
        "title": name,
        "year": None,
        "genre": _extract_spotify_genre(item),
        "quality": None,
    }


def _normalise_plex_entry(
    entry: Dict[str, Any],
    query_lower: str,
    filters: SearchFilters,
) -> Dict[str, Any] | None:
    title = str(entry.get("title") or "").strip()
    album = str(entry.get("parentTitle") or "").strip()
    artist = str(entry.get("grandparentTitle") or "").strip()
    rating_key = entry.get("ratingKey")

    if any([title, album, artist]):
        haystack = " ".join(filter(None, [title.lower(), album.lower(), artist.lower()]))
        if query_lower not in haystack:
            return None
    else:
        return None

    year = _parse_year(entry.get("year"))
    if filters.year is not None and year not in {filters.year, None}:
        return None

    genres = _extract_plex_genres(entry)
    if filters.genre and (
        not genres
        or not any(_genre_matches(genre, filters.genre) for genre in genres)
    ):
        return None

    quality = _extract_plex_quality(entry.get("Media"))
    if filters.quality and not _quality_matches(quality, filters.quality):
        return None

    identifier = rating_key or title or album or artist or query_lower
    return {
        "id": str(identifier),
        "source": "plex",
        "type": "track",
        "artist": artist or None,
        "album": album or None,
        "title": title or str(identifier),
        "year": year,
        "genre": genres[0] if genres else None,
        "quality": quality,
    }


def _extract_plex_genres(entry: Dict[str, Any]) -> list[str]:
    genres: list[str] = []
    raw = entry.get("Genre")
    if isinstance(raw, list):
        for item in raw:
            label = _normalise_genre_label(item)
            if label:
                genres.append(label)
    elif raw is not None:
        label = _normalise_genre_label(raw)
        if label:
            genres.append(label)
    raw_genre = _normalise_genre_label(entry.get("genre"))
    if raw_genre:
        genres.append(raw_genre)
    # preserve order but drop duplicates
    seen: set[str] = set()
    unique: list[str] = []
    for label in genres:
        lowered = label.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(label)
    return unique


def _extract_plex_quality(media_payload: Any) -> str | None:
    media: Dict[str, Any] = {}
    if isinstance(media_payload, list) and media_payload:
        first = media_payload[0]
        if isinstance(first, dict):
            media = first
    elif isinstance(media_payload, dict):
        media = media_payload

    codec = media.get("audioCodec") or media.get("codec") or media.get("container")
    bitrate = media.get("bitrate")
    return _build_quality_label(codec, bitrate)


def _normalise_soulseek_results(payload: Any, filters: SearchFilters) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        extracted = payload.get("results")
        if isinstance(extracted, list):
            items = extracted
        elif extracted is None:
            items = []
        else:
            items = [extracted]
    elif isinstance(payload, list):
        items = payload
    elif payload:
        items = [payload]
    else:
        items = []

    results: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            files = item.get("files")
            if isinstance(files, list) and files:
                for file_info in files:
                    normalised = _normalise_soulseek_file(item, file_info, filters)
                    if normalised is not None:
                        results.append(normalised)
                continue
            normalised = _normalise_soulseek_file(item, item, filters)
            if normalised is not None:
                results.append(normalised)
        else:
            if filters.quality:
                continue
            title = str(item).strip()
            if not title:
                continue
            results.append(
                {
                    "id": title,
                    "source": "soulseek",
                    "type": "file",
                    "artist": None,
                    "album": None,
                    "title": title,
                    "year": None,
                    "genre": None,
                    "quality": None,
                }
            )
    return results


def _normalise_soulseek_file(
    container: Dict[str, Any],
    file_info: Any,
    filters: SearchFilters,
) -> Dict[str, Any] | None:
    if not isinstance(file_info, dict):
        return None

    title = str(
        file_info.get("title")
        or file_info.get("filename")
        or container.get("title")
        or container.get("filename")
        or ""
    ).strip()
    if not title:
        return None

    artist = str(file_info.get("artist") or container.get("artist") or "").strip()
    album = str(file_info.get("album") or container.get("album") or "").strip()
    year = _parse_year(file_info.get("year") or container.get("year"))

    if filters.year is not None and year not in {filters.year, None}:
        return None

    genre_value = file_info.get("genre") or container.get("genre")
    genre_label = _normalise_genre_label(genre_value)
    if filters.genre and not _genre_matches(genre_label, filters.genre):
        return None

    codec = (
        file_info.get("format")
        or file_info.get("codec")
        or file_info.get("extension")
        or container.get("format")
    )
    bitrate = file_info.get("bitrate") or container.get("bitrate")
    quality = _build_quality_label(codec, bitrate)
    if filters.quality and not _quality_matches(quality, filters.quality):
        return None

    identifier = (
        file_info.get("id")
        or file_info.get("download_id")
        or file_info.get("filename")
        or title
    )
    return {
        "id": str(identifier),
        "source": "soulseek",
        "type": "file",
        "artist": artist or None,
        "album": album or None,
        "title": title,
        "year": year,
        "genre": genre_label,
        "quality": quality,
    }


def _extract_spotify_genre(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    genre = _normalise_genre_label(payload.get("genre"))
    if genre:
        return genre
    genres_value = payload.get("genres")
    if genres_value is None and "genre" in payload:
        genres_value = payload["genre"]
    return _normalise_genre_label(genres_value)


def _build_quality_label(codec: Any, bitrate: Any) -> str | None:
    codec_str = str(codec).strip().upper() if codec else ""
    bitrate_value: int | None = None
    if isinstance(bitrate, (int, float)):
        bitrate_value = int(bitrate)
    else:
        try:
            bitrate_value = int(str(bitrate))
        except (TypeError, ValueError):
            bitrate_value = None

    parts: list[str] = []
    if codec_str:
        parts.append(codec_str)
    if bitrate_value and bitrate_value > 0:
        parts.append(f"{bitrate_value}kbps")
    if not parts:
        return None
    return " ".join(parts)


def _normalise_genre_label(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, dict):
        for key in ("tag", "name", "label", "title"):
            if key in value:
                return _normalise_genre_label(value.get(key))
        return None
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        for entry in value:
            label = _normalise_genre_label(entry)
            if label:
                return label
    return None


def _genre_matches(value: str | None, requested: str | None) -> bool:
    if not requested:
        return True
    if not value:
        return False
    return requested.lower() in value.lower()


def _quality_matches(available: str | None, requested: str | None) -> bool:
    if not requested:
        return True
    if not available:
        return False
    return requested.lower() in available.lower()


def _parse_year(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) >= 4 and stripped[:4].isdigit():
            return int(stripped[:4])
    return None


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


def _missing_credentials() -> dict[str, tuple[str, ...]]:
    with session_scope() as session:
        return collect_missing_credentials(session, REQUIRED_SERVICES)

