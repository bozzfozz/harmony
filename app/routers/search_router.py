"""Unified search endpoint aggregating Spotify, Plex and Soulseek."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.core.matching_engine import MusicMatchingEngine
from app.core.plex_client import PlexClient
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.dependencies import (
    get_matching_engine,
    get_plex_client,
    get_soulseek_client,
    get_spotify_client,
)
from app.logging import get_logger
from app.schemas_search import (
    ItemTypeLiteral,
    SearchFilters,
    SearchItem,
    SearchRequest,
    SearchResponse,
    SortByLiteral,
)


logger = get_logger(__name__)
router = APIRouter()

DEFAULT_SOURCES: Tuple[str, ...] = ("spotify", "plex", "soulseek")


@router.post("/search", response_model=SearchResponse, response_model_exclude_none=True)
async def unified_search(
    request: SearchRequest,
    spotify_client: SpotifyClient = Depends(get_spotify_client),
    plex_client: PlexClient = Depends(get_plex_client),
    soulseek_client: SoulseekClient = Depends(get_soulseek_client),
    matching_engine: MusicMatchingEngine = Depends(get_matching_engine),
) -> SearchResponse:
    """Aggregate search results across all configured music sources."""

    filters = request.filters
    preferred_formats = {value.lower() for value in (filters.preferred_formats or [])}
    sources = request.sources or list(DEFAULT_SOURCES)

    tasks: list[tuple[str, asyncio.Task[tuple[List[SearchItem], Optional[str]]]]] = []
    if "spotify" in sources:
        tasks.append(
            (
                "spotify",
                asyncio.create_task(
                    _search_spotify(
                        request.query,
                        filters,
                        spotify_client,
                        matching_engine,
                        preferred_formats,
                    )
                ),
            )
        )
    if "plex" in sources:
        tasks.append(
            (
                "plex",
                asyncio.create_task(
                    _search_plex(
                        request.query,
                        filters,
                        plex_client,
                        matching_engine,
                        preferred_formats,
                    )
                ),
            )
        )
    if "soulseek" in sources:
        tasks.append(
            (
                "soulseek",
                asyncio.create_task(
                    _search_soulseek(
                        request.query,
                        filters,
                        soulseek_client,
                        matching_engine,
                        preferred_formats,
                    )
                ),
            )
        )

    aggregated: list[SearchItem] = []
    errors: Dict[str, str] = {}
    for source, task in tasks:
        try:
            items, source_error = await task
            aggregated.extend(items)
            if source_error:
                errors[source] = source_error
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Search source %s failed: %s", source, exc)
            errors[source] = f"{source.capitalize()} source unavailable"

    filtered = _filter_items(aggregated, filters)
    sorted_items = _sort_items(filtered, request.sort.by, request.sort.order)
    total = len(sorted_items)

    page = request.pagination.page
    size = request.pagination.size
    start = max((page - 1) * size, 0)
    end = start + size
    page_items = sorted_items[start:end]

    return SearchResponse(
        page=page,
        size=size,
        total=total,
        items=page_items,
        errors=errors or None,
    )


async def _search_spotify(
    query: str,
    filters: SearchFilters,
    client: SpotifyClient,
    matching_engine: MusicMatchingEngine,
    preferred_formats: set[str],
) -> tuple[List[SearchItem], Optional[str]]:
    search_types = set(filters.types or ("track", "album", "artist"))
    results: list[SearchItem] = []

    if "track" in search_types:
        response = await run_in_threadpool(client.search_tracks, query, 50)
        for item in _extract_spotify_items(response, "tracks"):
            results.append(
                _build_spotify_item(
                    query,
                    item,
                    "track",
                    matching_engine,
                    filters,
                    preferred_formats,
                )
            )

    if "album" in search_types:
        response = await run_in_threadpool(client.search_albums, query, 50)
        for item in _extract_spotify_items(response, "albums"):
            results.append(
                _build_spotify_item(
                    query,
                    item,
                    "album",
                    matching_engine,
                    filters,
                    preferred_formats,
                )
            )

    if "artist" in search_types:
        response = await run_in_threadpool(client.search_artists, query, 50)
        for item in _extract_spotify_items(response, "artists"):
            results.append(
                _build_spotify_item(
                    query,
                    item,
                    "artist",
                    matching_engine,
                    filters,
                    preferred_formats,
                )
            )

    return results, None


async def _search_plex(
    query: str,
    filters: SearchFilters,
    client: PlexClient,
    matching_engine: MusicMatchingEngine,
    preferred_formats: set[str],
) -> tuple[List[SearchItem], Optional[str]]:
    search_types = tuple(filters.types or ("track", "album", "artist"))
    try:
        entries = await client.search_music(query, mediatypes=search_types, limit=60)
    except Exception as exc:
        logger.warning("Plex search failed directly, falling back to manual lookup: %s", exc)
        return [], "Plex source unavailable"

    results: list[SearchItem] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalised = client.normalise_music_entry(entry)
        item_type = normalised.get("type") or "track"
        rating_key = normalised.get("id") or entry.get("ratingKey")
        identifier = str(rating_key) if rating_key else _fallback_identifier(entry)
        candidate = {
            "title": normalised.get("title"),
            "album": normalised.get("album"),
            "artists": normalised.get("artists"),
            "type": item_type,
        }
        score = _calculate_score(
            matching_engine,
            query,
            candidate,
            filters,
            normalised.get("bitrate"),
            normalised.get("format"),
            preferred_formats,
        )
        results.append(
            SearchItem(
                id=f"plex:{item_type}:{identifier}",
                type=item_type,  # type: ignore[arg-type]
                source="plex",
                title=str(normalised.get("title") or entry.get("title") or ""),
                artists=list(normalised.get("artists") or []),
                album=normalised.get("album"),
                year=normalised.get("year"),
                duration_ms=normalised.get("duration_ms"),
                bitrate=normalised.get("bitrate"),
                format=normalised.get("format"),
                score=score,
                genres=list(normalised.get("genres") or []),
                extra={
                    "ratingKey": rating_key,
                    **(normalised.get("extra") or {}),
                },
            )
        )
    return results, None


async def _search_soulseek(
    query: str,
    filters: SearchFilters,
    client: SoulseekClient,
    matching_engine: MusicMatchingEngine,
    preferred_formats: set[str],
) -> tuple[List[SearchItem], Optional[str]]:
    try:
        payload = await client.search(query)
    except Exception as exc:
        logger.warning("Soulseek search failed: %s", exc)
        raise

    entries = client.normalise_search_results(payload)
    results: list[SearchItem] = []
    for entry in entries:
        candidate = {
            "title": entry.get("title"),
            "album": entry.get("album"),
            "artists": entry.get("artists"),
            "type": "track",
        }
        score = _calculate_score(
            matching_engine,
            query,
            candidate,
            filters,
            entry.get("bitrate"),
            entry.get("format"),
            preferred_formats,
        )
        identifier = entry.get("id") or entry.get("extra", {}).get("path")
        resolved_id = identifier or entry.get("title") or "unknown"
        results.append(
            SearchItem(
                id=f"soulseek:file:{resolved_id}",
                type="track",
                source="soulseek",
                title=str(entry.get("title") or ""),
                artists=list(entry.get("artists") or []),
                album=entry.get("album"),
                year=entry.get("year"),
                duration_ms=entry.get("duration_ms"),
                bitrate=entry.get("bitrate"),
                format=entry.get("format"),
                score=score,
                genres=list(entry.get("genres") or []),
                extra=entry.get("extra") or {},
            )
        )
    return results, None


def _extract_spotify_items(payload: Any, key: str) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    section = payload.get(key)
    if isinstance(section, dict):
        items = section.get("items")
    else:
        items = payload.get("items") if key == "items" else None
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _build_spotify_item(
    query: str,
    payload: Dict[str, Any],
    item_type: ItemTypeLiteral,
    matching_engine: MusicMatchingEngine,
    filters: SearchFilters,
    preferred_formats: set[str],
) -> SearchItem:
    identifier = payload.get("uri") or payload.get("id") or "unknown"
    spotify_id = str(identifier)
    if ":" not in spotify_id and payload.get("id"):
        spotify_id = f"spotify:{item_type}:{payload['id']}"

    title = str(payload.get("name") or payload.get("title") or "")
    artists_payload = payload.get("artists") or payload.get("artist")
    if isinstance(artists_payload, list):
        artists = [
            str(entry.get("name") if isinstance(entry, dict) else entry)
            for entry in artists_payload
            if entry
        ]
        artist_ids = [
            entry.get("id")
            for entry in artists_payload
            if isinstance(entry, dict) and entry.get("id")
        ]
    elif isinstance(artists_payload, dict):
        artists = [str(artists_payload.get("name") or "")]
        artist_ids = [artists_payload.get("id")] if artists_payload.get("id") else []
    elif artists_payload:
        artists = [str(artists_payload)]
        artist_ids = []
    else:
        artists = []
        artist_ids = []

    album_info = payload.get("album") if isinstance(payload.get("album"), dict) else None
    album_title = None
    release_date = None
    if album_info:
        album_title = album_info.get("name")
        release_date = album_info.get("release_date") or album_info.get("releaseDate")
    elif item_type == "album":
        album_title = payload.get("name")
        release_date = payload.get("release_date")

    year = _parse_year(release_date)

    duration_value = payload.get("duration_ms") or payload.get("duration")
    duration_ms = _coerce_int(duration_value)

    explicit = payload.get("explicit") if item_type == "track" else None

    genres_raw = payload.get("genres")
    if isinstance(genres_raw, list):
        genres = [str(entry) for entry in genres_raw if entry]
    else:
        genre_single = payload.get("genre")
        genres = [str(genre_single)] if genre_single else []

    candidate = {
        "title": title,
        "album": album_title if item_type != "artist" else None,
        "artists": artists,
        "type": item_type,
    }
    score = _calculate_score(
        matching_engine,
        query,
        candidate,
        filters,
        None,
        None,
        preferred_formats,
    )

    extra: Dict[str, Any] = {}
    if album_info and album_info.get("id"):
        extra["spotify_album_id"] = album_info.get("id")
    if artist_ids:
        extra["spotify_artist_ids"] = [str(value) for value in artist_ids]
    if payload.get("popularity") is not None:
        extra["popularity"] = payload.get("popularity")

    return SearchItem(
        id=spotify_id,
        type=item_type,
        source="spotify",
        title=title,
        artists=artists,
        album=album_title if item_type != "artist" else None,
        year=year,
        duration_ms=duration_ms if item_type == "track" else None,
        explicit=explicit,
        score=score,
        genres=genres,
        extra=extra,
    )


def _calculate_score(
    matching_engine: MusicMatchingEngine,
    query: str,
    candidate: Dict[str, Any],
    filters: SearchFilters,
    bitrate: Optional[int],
    audio_format: Optional[str],
    preferred_formats: set[str],
) -> float:
    base_score = matching_engine.compute_relevance_score(query, candidate)
    score = base_score

    normalised_query = query.strip().lower()
    candidate_title = str(candidate.get("title") or "").strip().lower()
    if candidate_title and candidate_title == normalised_query:
        score = max(score, 0.9)

    if audio_format and audio_format.lower() in preferred_formats:
        score += 0.05

    if filters.min_bitrate is not None and bitrate is not None:
        if bitrate >= filters.min_bitrate:
            score += 0.03
    elif bitrate is not None:
        score += min(bitrate / 320.0, 1.0) * 0.01

    return min(score, 1.0)


def _filter_items(items: Iterable[SearchItem], filters: SearchFilters) -> List[SearchItem]:
    type_set = set(filters.types or []) or None
    genre_set = {genre.lower() for genre in (filters.genres or [])} or None
    year_range = filters.year_range
    duration_range = filters.duration_ms
    explicit_filter = filters.explicit
    min_bitrate = filters.min_bitrate
    username = filters.username.lower() if filters.username else None

    filtered: list[SearchItem] = []
    for item in items:
        if type_set and item.type not in type_set:
            continue
        if genre_set:
            item_genres = {genre.lower() for genre in item.genres}
            if not item_genres.intersection(genre_set):
                continue
        if year_range is not None:
            start, end = year_range
            if item.year is None:
                continue
            if start is not None and item.year < start:
                continue
            if end is not None and item.year > end:
                continue
        if duration_range is not None:
            start, end = duration_range
            if item.duration_ms is None:
                continue
            if start is not None and item.duration_ms < start:
                continue
            if end is not None and item.duration_ms > end:
                continue
        if explicit_filter is not None:
            if item.explicit is None or item.explicit is not explicit_filter:
                continue
        if min_bitrate is not None:
            if item.bitrate is None or item.bitrate < min_bitrate:
                continue
        if username is not None:
            candidate_username = str(item.extra.get("username") or "").strip().lower()
            if candidate_username != username:
                continue
        filtered.append(item)
    return filtered


def _sort_items(items: List[SearchItem], sort_by: SortByLiteral, order: str) -> List[SearchItem]:
    reverse = order.lower() == "desc"

    def _primary(item: SearchItem) -> float:
        if sort_by == "bitrate":
            if item.bitrate is None:
                return float("-inf") if reverse else float("inf")
            return float(item.bitrate)
        if sort_by == "year":
            if item.year is None:
                return float("-inf") if reverse else float("inf")
            return float(item.year)
        if sort_by == "duration":
            if item.duration_ms is None:
                return float("-inf") if reverse else float("inf")
            return float(item.duration_ms)
        return float(item.score)

    return sorted(
        items,
        key=lambda item: (
            _primary(item),
            float(item.score),
            float(item.bitrate or 0),
            float(item.year or 0),
            float(item.duration_ms or 0),
            item.title.lower(),
            item.id,
        ),
        reverse=reverse,
    )


def _parse_year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    text = str(value)
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    if text.isdigit():
        return int(text)
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _fallback_identifier(entry: Dict[str, Any]) -> str:
    title = str(entry.get("title") or "")
    if title:
        return title.lower().replace(" ", "-")
    try:
        return str(hash(frozenset(entry.items())))
    except TypeError:  # pragma: no cover - fallback for unhashable payloads
        return str(hash(str(entry)))
