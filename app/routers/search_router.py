"""Smart search endpoint aggregating Spotify, Plex and Soulseek."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Dict, Iterable, Optional, Sequence, cast

from fastapi import APIRouter, Depends, HTTPException, status
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
    SearchItem,
    SearchRequest,
    SearchResponse,
    SourceLiteral,
)
from app.utils.normalize import (
    boost_for_bitrate,
    boost_for_format,
    clamp_score,
    format_priority_index,
    normalize_genres,
    normalize_text,
    year_distance_bonus,
)


logger = get_logger(__name__)

DEFAULT_SOURCES: tuple[SourceLiteral, ...] = ("spotify", "plex", "soulseek")
SEARCH_TIMEOUT_MS = int(os.getenv("SEARCH_TIMEOUT_MS", "8000") or "8000")
SEARCH_TIMEOUT_SECONDS = max(0.1, SEARCH_TIMEOUT_MS / 1000)
SEARCH_MAX_LIMIT = int(os.getenv("SEARCH_MAX_LIMIT", "100") or "100")
TOTAL_RESULT_CAP = 1000
PER_SOURCE_FETCH_LIMIT = 60


@dataclass(slots=True)
class Candidate:
    """Intermediate representation of a search result before scoring."""

    type: ItemTypeLiteral
    id: str
    source: SourceLiteral
    title: str
    artists: list[str]
    album: Optional[str]
    year: Optional[int]
    genres: list[str]
    bitrate: Optional[int]
    audio_format: Optional[str]
    raw: dict[str, Any]

    @property
    def primary_artist(self) -> Optional[str]:
        return self.artists[0] if self.artists else None


router = APIRouter(prefix="/api", tags=["Search"])


@router.post("/search", response_model=SearchResponse, status_code=status.HTTP_200_OK)
async def smart_search(
    request: SearchRequest,
    spotify_client: SpotifyClient = Depends(get_spotify_client),
    plex_client: PlexClient = Depends(get_plex_client),
    soulseek_client: SoulseekClient = Depends(get_soulseek_client),
    matching_engine: MusicMatchingEngine = Depends(get_matching_engine),
) -> SearchResponse:
    """Aggregate search results from Spotify, Plex and Soulseek with ranking."""

    resolved_sources = request.sources or list(DEFAULT_SOURCES)
    limit = min(request.limit, SEARCH_MAX_LIMIT)
    offset = request.offset

    tasks: list[tuple[SourceLiteral, asyncio.Task[tuple[list[Candidate], Optional[str]]]]] = []

    if "spotify" in resolved_sources:
        tasks.append(
            (
                "spotify",
                asyncio.create_task(
                    _execute_source(
                        "spotify",
                        _search_spotify(request, spotify_client),
                    )
                ),
            )
        )
    if "plex" in resolved_sources:
        tasks.append(
            (
                "plex",
                asyncio.create_task(
                    _execute_source(
                        "plex",
                        _search_plex(request, plex_client),
                    )
                ),
            )
        )
    if "soulseek" in resolved_sources:
        tasks.append(
            (
                "soulseek",
                asyncio.create_task(
                    _execute_source(
                        "soulseek",
                        _search_soulseek(request, soulseek_client),
                    )
                ),
            )
        )

    aggregated: list[Candidate] = []
    failures: Dict[str, str] = {}

    started = time.perf_counter()
    for source, task in tasks:
        items, error = await task
        if error:
            failures[source] = error
        aggregated.extend(items)

    if failures and len(failures) == len(tasks):
        logger.error(
            "Search failed for all sources", extra={"event": "search", "sources": resolved_sources}
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "ok": False,
                "code": "DEPENDENCY_ERROR",
                "message": "All search sources failed",
                "errors": failures,
            },
        )

    filtered = _apply_filters(aggregated, request)

    scored_items = _score_and_sort(filtered, request, matching_engine)

    capped_items = scored_items[:TOTAL_RESULT_CAP]
    page_items = capped_items[offset : offset + limit]

    duration_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "Smart search completed",
        extra={
            "event": "search",
            "query": request.query,
            "sources": resolved_sources,
            "duration_ms": round(duration_ms, 2),
            "total_before_paging": len(scored_items),
            "partial_failures": sorted(failures.keys()),
        },
    )

    return SearchResponse(
        ok=not failures,
        total=len(scored_items),
        limit=limit,
        offset=offset,
        items=page_items,
    )


async def _execute_source(
    source: SourceLiteral, coroutine: Awaitable[list[Candidate]]
) -> tuple[list[Candidate], Optional[str]]:
    try:
        items = await asyncio.wait_for(coroutine, timeout=SEARCH_TIMEOUT_SECONDS)
        return items, None
    except asyncio.TimeoutError:
        logger.warning("Search source %s timed out", source)
        return [], f"{source.capitalize()} search timed out"
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Search source %s failed: %s", source, exc)
        return [], f"{source.capitalize()} source unavailable"


async def _search_spotify(request: SearchRequest, client: SpotifyClient) -> list[Candidate]:
    """Query Spotify for artists, albums and tracks."""

    search_types = _resolve_types(request.type)
    tasks: list[asyncio.Task[Dict[str, Any]]] = []

    if "track" in search_types:
        tasks.append(
            asyncio.create_task(
                run_in_threadpool(
                    client.search_tracks,
                    request.query,
                    PER_SOURCE_FETCH_LIMIT,
                    genre=request.genre,
                    year_from=request.year_from,
                    year_to=request.year_to,
                )
            )
        )
    if "album" in search_types:
        tasks.append(
            asyncio.create_task(
                run_in_threadpool(
                    client.search_albums,
                    request.query,
                    PER_SOURCE_FETCH_LIMIT,
                    genre=request.genre,
                    year_from=request.year_from,
                    year_to=request.year_to,
                )
            )
        )
    if "artist" in search_types:
        tasks.append(
            asyncio.create_task(
                run_in_threadpool(
                    client.search_artists,
                    request.query,
                    PER_SOURCE_FETCH_LIMIT,
                    genre=request.genre,
                    year_from=request.year_from,
                    year_to=request.year_to,
                )
            )
        )

    if not tasks:
        return []

    payloads = await asyncio.gather(*tasks, return_exceptions=True)

    candidates: list[Candidate] = []
    errors = 0
    for payload in payloads:
        if isinstance(payload, Exception):  # pragma: no cover - handled by caller
            logger.warning("Spotify search payload failed: %s", payload)
            errors += 1
            continue
        candidates.extend(_extract_spotify_candidates(payload))
    if errors and errors == len(payloads):
        raise RuntimeError("Spotify search failed")
    return candidates


async def _search_plex(request: SearchRequest, client: PlexClient) -> list[Candidate]:
    mediatypes = tuple(_resolve_types(request.type)) or ("track", "album", "artist")
    entries = await client.search_music(
        request.query,
        mediatypes=mediatypes,
        limit=PER_SOURCE_FETCH_LIMIT,
        genre=request.genre,
        year_from=request.year_from,
        year_to=request.year_to,
    )
    candidates: list[Candidate] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalised = client.normalise_music_entry(entry)
        item_type = str(normalised.get("type") or "track")
        genres = normalize_genres(normalised.get("genres", []))
        bitrate = _coerce_int(normalised.get("bitrate"))
        audio_format = _normalise_format(normalised.get("format"))
        artists = [str(name) for name in normalised.get("artists", []) if name]
        identifier = (
            normalised.get("id") or entry.get("ratingKey") or normalised.get("title") or "unknown"
        )
        identifier_str = str(identifier)
        candidate = Candidate(
            type=cast(
                ItemTypeLiteral, item_type if item_type in {"track", "album", "artist"} else "track"
            ),
            id=f"plex:{item_type}:{identifier_str}",
            source="plex",
            title=str(normalised.get("title") or entry.get("title") or ""),
            artists=artists,
            album=normalised.get("album"),
            year=_coerce_int(normalised.get("year")),
            genres=genres,
            bitrate=bitrate,
            audio_format=audio_format,
            raw={"entry": entry, "normalised": normalised},
        )
        candidates.append(candidate)
    return candidates


async def _search_soulseek(request: SearchRequest, client: SoulseekClient) -> list[Candidate]:
    payload = await client.search(
        request.query,
        min_bitrate=request.min_bitrate,
        format_priority=request.format_priority or [],
    )
    entries = client.normalise_search_results(payload)
    candidates: list[Candidate] = []
    for entry in entries:
        genres = normalize_genres(entry.get("genres", []))
        bitrate = _coerce_int(entry.get("bitrate"))
        audio_format = _normalise_format(entry.get("format"))
        artists = [str(name) for name in entry.get("artists", []) if name]
        identifier = (
            entry.get("id") or entry.get("extra", {}).get("path") or entry.get("title") or "unknown"
        )
        identifier_str = str(identifier)
        candidate = Candidate(
            type="track",
            id=f"soulseek:file:{identifier_str}",
            source="soulseek",
            title=str(entry.get("title") or entry.get("filename") or ""),
            artists=artists,
            album=entry.get("album"),
            year=_coerce_int(entry.get("year")),
            genres=genres,
            bitrate=bitrate,
            audio_format=audio_format,
            raw=entry,
        )
        candidates.append(candidate)
    return candidates


def _resolve_types(request_type: str) -> list[ItemTypeLiteral]:
    if request_type == "mixed":
        return ["artist", "album", "track"]
    return [cast(ItemTypeLiteral, request_type)]


def _extract_spotify_candidates(payload: Dict[str, Any]) -> list[Candidate]:
    candidates: list[Candidate] = []
    if not isinstance(payload, dict):
        return candidates

    for section, item_type in (("tracks", "track"), ("albums", "album"), ("artists", "artist")):
        container = payload.get(section)
        items = None
        if isinstance(container, dict):
            items = container.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            candidates.append(_build_spotify_candidate(item, item_type))
    return candidates


def _build_spotify_candidate(payload: Dict[str, Any], item_type: str) -> Candidate:
    title = str(payload.get("name") or payload.get("title") or "")
    artists_field = payload.get("artists") or payload.get("artist")
    artists: list[str] = []
    if isinstance(artists_field, list):
        for entry in artists_field:
            if isinstance(entry, dict):
                name = entry.get("name")
                if name:
                    artists.append(str(name))
            elif entry:
                artists.append(str(entry))
    elif isinstance(artists_field, dict):
        name = artists_field.get("name")
        if name:
            artists.append(str(name))
    elif artists_field:
        artists.append(str(artists_field))

    album_info = payload.get("album") if isinstance(payload.get("album"), dict) else None
    album_title = album_info.get("name") if isinstance(album_info, dict) else None
    release_date = None
    if album_info and isinstance(album_info, dict):
        release_date = album_info.get("release_date") or album_info.get("releaseDate")
    elif item_type == "album":
        release_date = payload.get("release_date")

    genres_field = payload.get("genres")
    if isinstance(genres_field, list):
        genres = normalize_genres(genres_field)
    else:
        single_genre = payload.get("genre")
        genres = normalize_genres([single_genre] if single_genre else [])
    audio_format = _normalise_format(payload.get("format"))

    identifier = payload.get("uri") or payload.get("id") or "unknown"
    spotify_id = str(identifier)
    if ":" not in spotify_id and payload.get("id"):
        spotify_id = f"spotify:{item_type}:{payload['id']}"

    candidate = Candidate(
        type=cast(ItemTypeLiteral, item_type),
        id=spotify_id,
        source="spotify",
        title=title,
        artists=artists,
        album=album_title if item_type != "artist" else None,
        year=_parse_year(release_date),
        genres=genres,
        bitrate=None,
        audio_format=audio_format,
        raw=payload,
    )
    return candidate


def _apply_filters(candidates: Iterable[Candidate], request: SearchRequest) -> list[Candidate]:
    filtered: list[Candidate] = []
    genre_filter = normalize_text(request.genre) if request.genre else None
    for candidate in candidates:
        if request.type != "mixed" and candidate.type != request.type:
            continue
        if request.genre and not _genre_matches(candidate.genres, genre_filter):
            continue
        if request.year_from is not None and (
            candidate.year is None or candidate.year < request.year_from
        ):
            continue
        if request.year_to is not None and (
            candidate.year is None or candidate.year > request.year_to
        ):
            continue
        if (
            request.min_bitrate is not None
            and candidate.bitrate is not None
            and candidate.bitrate < request.min_bitrate
        ):
            continue
        filtered.append(candidate)
    return filtered


def _genre_matches(genres: Sequence[str], genre_filter: Optional[str]) -> bool:
    if not genre_filter:
        return True
    for genre in genres:
        if genre_filter in normalize_text(genre):
            return True
    return False


def _score_and_sort(
    candidates: Iterable[Candidate],
    request: SearchRequest,
    matching_engine: MusicMatchingEngine,
) -> list[SearchItem]:
    priority = request.format_priority or []
    sortable: list[tuple[SearchItem, float, int, int]] = []

    for candidate in candidates:
        base_payload = {
            "title": candidate.title,
            "album": candidate.album,
            "artists": candidate.artists,
            "type": candidate.type,
        }
        base_score = matching_engine.compute_relevance_score(request.query, base_payload)
        score = clamp_score(
            base_score
            + boost_for_format(candidate.audio_format)
            + boost_for_bitrate(candidate.bitrate)
            + year_distance_bonus(candidate.year, request.year_from, request.year_to)
            + (0.1 if request.type != "mixed" and candidate.type == request.type else 0.0)
        )
        metadata: Dict[str, Any] = {"raw": candidate.raw}
        if candidate.artists:
            metadata["artists"] = candidate.artists
        item = SearchItem(
            type=candidate.type,
            id=candidate.id,
            source=candidate.source,
            title=candidate.title,
            artist=candidate.primary_artist,
            album=candidate.album,
            year=candidate.year,
            genres=candidate.genres,
            bitrate=candidate.bitrate,
            format=candidate.audio_format,
            score=score,
            metadata=metadata,
        )
        format_rank = format_priority_index(candidate.audio_format, priority)
        bitrate_value = candidate.bitrate or 0
        year_value = candidate.year or 0
        sortable.append((item, score, format_rank, bitrate_value, year_value))

    sortable.sort(
        key=lambda data: (
            -data[1],  # score desc
            data[2],  # format priority asc
            -(data[3]),  # bitrate desc
            -(data[4]),  # year desc
            normalize_text(data[0].title),
            data[0].id,
        )
    )

    return [item for item, *_ in sortable]


def _normalise_format(value: Any) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    return text.upper() or None


def _parse_year(value: Any) -> Optional[int]:
    if not value:
        return None
    text = str(value)
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    if text.isdigit():
        return int(text)
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
