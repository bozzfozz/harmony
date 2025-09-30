"""Smart search endpoint aggregating Spotify and Soulseek."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from fastapi import APIRouter, Depends, Request, status

from app.core.matching_engine import MusicMatchingEngine
from app.dependencies import get_matching_engine, get_provider_gateway
from app.errors import DependencyError
from app.logging import get_logger
from app.logging_events import log_event
from app.integrations.base import TrackCandidate
from app.integrations.contracts import ProviderTrack, SearchQuery
from app.integrations.provider_gateway import ProviderGateway, ProviderGatewaySearchResponse
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

DEFAULT_SOURCES: tuple[SourceLiteral, ...] = ("spotify", "soulseek")
SEARCH_MAX_LIMIT = int(os.getenv("SEARCH_MAX_LIMIT", "100") or "100")
TOTAL_RESULT_CAP = 1000
PER_SOURCE_FETCH_LIMIT = 60

SOURCE_TO_PROVIDER: dict[SourceLiteral, str] = {
    "spotify": "spotify",
    "soulseek": "slskd",
}
PROVIDER_TO_SOURCE: dict[str, SourceLiteral] = {
    value: key for key, value in SOURCE_TO_PROVIDER.items()
}


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


router = APIRouter(tags=["Search"])


@router.post("/search", response_model=SearchResponse, status_code=status.HTTP_200_OK)
async def smart_search(
    request: SearchRequest,
    raw_request: Request,
    matching_engine: MusicMatchingEngine = Depends(get_matching_engine),
    gateway: ProviderGateway = Depends(get_provider_gateway),
) -> SearchResponse:
    """Aggregate search results from Spotify and Soulseek with ranking."""

    resolved_sources = request.sources or list(DEFAULT_SOURCES)
    limit = min(request.limit, SEARCH_MAX_LIMIT)
    offset = request.offset

    provider_names: list[str] = []
    for source in resolved_sources:
        provider = SOURCE_TO_PROVIDER.get(source)
        if provider and provider not in provider_names:
            provider_names.append(provider)

    search_query = SearchQuery(text=request.query, artist=None, limit=PER_SOURCE_FETCH_LIMIT)

    started = time.perf_counter()
    try:
        gateway_response = await gateway.search_many(provider_names, search_query)
    except KeyError as exc:
        logger.error("Requested provider not available", exc_info=exc)
        raise DependencyError(
            "Requested search source is not available",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    aggregated, failures = _collect_candidates(gateway_response)

    if gateway_response.status == "failed":
        logger.error(
            "Search failed for all sources", extra={"event": "search", "sources": resolved_sources}
        )
        raise DependencyError(
            "All search sources failed",
            meta={"failures": failures},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    filtered = _apply_filters(aggregated, request)

    scored_items = _score_and_sort(filtered, request, matching_engine)

    capped_items = scored_items[:TOTAL_RESULT_CAP]
    page_items = capped_items[offset : offset + limit]

    duration_ms = (time.perf_counter() - started) * 1000
    status_value = gateway_response.status
    log_event(
        logger,
        "api.request",
        component="router.search",
        status=status_value,
        duration_ms=round(duration_ms, 2),
        entity_id=getattr(raw_request.state, "request_id", None),
        path=raw_request.url.path,
        method=raw_request.method,
        query=request.query,
        meta={
            "sources": resolved_sources,
            "total_before_paging": len(scored_items),
            "partial_failures": sorted(failures.keys()),
        },
    )

    return SearchResponse(
        ok=gateway_response.status != "failed",
        total=len(scored_items),
        limit=limit,
        offset=offset,
        items=page_items,
    )


def _collect_candidates(
    response: ProviderGatewaySearchResponse,
) -> tuple[list[Candidate], Dict[SourceLiteral, str]]:
    aggregated: list[Candidate] = []
    failures: Dict[SourceLiteral, str] = {}
    for result in response.results:
        source = PROVIDER_TO_SOURCE.get(result.provider.lower())
        if source is None:
            continue
        if result.error is not None:
            failures[source] = str(result.error)
            continue
        for track in result.tracks:
            aggregated.extend(_build_candidates_from_track(track, source))
    return aggregated, failures


def _build_candidates_from_track(
    track: ProviderTrack, source: SourceLiteral
) -> list[Candidate]:
    track_artists = [artist.name for artist in track.artists if artist.name]
    album_name = track.album.name if track.album else None
    track_metadata = _mapping_to_dict(track.metadata)
    album_metadata = _mapping_to_dict(track.album.metadata) if track.album else {}
    base_year = _extract_year(track_metadata, album_metadata)
    base_genres = _extract_genres(track_metadata, album_metadata)

    results: list[Candidate] = []
    if track.candidates:
        for candidate in track.candidates:
            candidate_metadata = _mapping_to_dict(candidate.metadata)
            genres = _extract_genres(candidate_metadata, track_metadata, album_metadata)
            year = _extract_year(candidate_metadata, track_metadata, album_metadata)
            bitrate = candidate.bitrate_kbps
            audio_format = _normalise_format(candidate.format)
            title = candidate.title or track.name
            artists = list(track_artists) or ([candidate.artist] if candidate.artist else [])
            metadata = _candidate_metadata(
                track=track,
                track_metadata=track_metadata,
                album_metadata=album_metadata,
                candidate=candidate,
                candidate_metadata=candidate_metadata,
            )
            identifier = _candidate_identifier(
                source,
                track_metadata,
                candidate_metadata,
                candidate.download_uri,
                title,
            )
            results.append(
                Candidate(
                    type="track",
                    id=identifier,
                    source=source,
                    title=title,
                    artists=artists,
                    album=album_name,
                    year=year or base_year,
                    genres=genres or base_genres,
                    bitrate=bitrate,
                    audio_format=audio_format,
                    raw=metadata,
                )
            )
    else:
        metadata = _candidate_metadata(
            track=track,
            track_metadata=track_metadata,
            album_metadata=album_metadata,
        )
        identifier = _candidate_identifier(source, track_metadata, None, None, track.name)
        results.append(
            Candidate(
                type="track",
                id=identifier,
                source=source,
                title=track.name,
                artists=track_artists,
                album=album_name,
                year=base_year,
                genres=base_genres,
                bitrate=None,
                audio_format=None,
                raw=metadata,
            )
        )
    return results


def _mapping_to_dict(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return {str(key): value for key, value in payload.items()}


def _candidate_metadata(
    *,
    track: ProviderTrack,
    track_metadata: Mapping[str, Any],
    album_metadata: Mapping[str, Any],
    candidate: TrackCandidate | None = None,
    candidate_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": track.provider,
        "track": {
            "name": track.name,
            "duration_ms": track.duration_ms,
            "isrc": track.isrc,
            "metadata": dict(track_metadata),
        },
    }
    if track.album is not None:
        payload["album"] = {
            "name": track.album.name,
            "id": track.album.id,
            "metadata": dict(album_metadata),
        }
    if candidate is not None:
        payload["candidate"] = {
            "title": candidate.title,
            "artist": candidate.artist,
            "format": candidate.format,
            "bitrate_kbps": candidate.bitrate_kbps,
            "size_bytes": candidate.size_bytes,
            "seeders": candidate.seeders,
            "username": candidate.username,
            "availability": candidate.availability,
            "download_uri": candidate.download_uri,
            "source": candidate.source,
            "metadata": dict(candidate_metadata or {}),
        }
    return payload


def _candidate_identifier(
    source: SourceLiteral,
    track_metadata: Mapping[str, Any],
    candidate_metadata: Mapping[str, Any] | None,
    download_uri: str | None,
    title: str,
) -> str:
    parts: list[str] = [source]
    track_id = track_metadata.get("uri") or track_metadata.get("id")
    if track_id:
        parts.append(str(track_id))
    if candidate_metadata:
        for key in ("id", "path", "filename", "download_id"):
            value = candidate_metadata.get(key)
            if value:
                parts.append(str(value))
                break
    if download_uri:
        parts.append(download_uri)
    if len(parts) == 1 and title:
        parts.append(normalize_text(title))
    identifier = ":".join(part for part in parts if part)
    return identifier or f"{source}:{normalize_text(title) if title else 'unknown'}"


def _extract_year(*sources: Mapping[str, Any] | None) -> Optional[int]:
    for mapping in sources:
        if not mapping:
            continue
        for key in ("year", "release_year", "releaseYear"):
            value = mapping.get(key)
            if value is not None:
                year = _coerce_int(value)
                if year is not None:
                    return year
        release_date = mapping.get("release_date")
        if release_date:
            parsed = _parse_year(release_date)
            if parsed is not None:
                return parsed
    return None


def _extract_genres(*sources: Mapping[str, Any] | None) -> list[str]:
    genres: list[str] = []
    for mapping in sources:
        if not mapping:
            continue
        raw = mapping.get("genres")
        if isinstance(raw, (list, tuple)):
            genres.extend(str(item) for item in raw if item)
        elif raw:
            genres.append(str(raw))
        single = mapping.get("genre")
        if single:
            genres.append(str(single))
    return normalize_genres(genres)


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
