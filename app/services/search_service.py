"""Service orchestrating the cross-provider search workflow."""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Iterable

from app.integrations.contracts import (
    ProviderTrack as GatewayProviderTrack,
)
from app.integrations.contracts import (
    SearchQuery as GatewaySearchQuery,
)
from app.logging import get_logger
from app.logging_events import log_event
from app.schemas.common import Paging, SourceEnum
from app.schemas.search import SearchItem, SearchQuery, SearchResponse
from app.services.errors import ServiceError, to_api_error
from app.services.integration_service import IntegrationService
from app.services.types import MatchingEngineProtocol

_SOURCE_TO_PROVIDER = {
    SourceEnum.SPOTIFY: "spotify",
    SourceEnum.SOULSEEK: "slskd",
}
_PROVIDER_TO_SOURCE = {value: key for key, value in _SOURCE_TO_PROVIDER.items()}
_JSON_PRIMITIVES = (str, int, float, bool, type(None))


class SearchService:
    """Thin orchestrator translating :class:`SearchQuery` into a response payload."""

    def __init__(
        self,
        *,
        integration_service: IntegrationService,
        matching_engine: MatchingEngineProtocol,
        fetch_limit: int = 60,
        max_results: int = 1000,
    ) -> None:
        self._integration = integration_service
        self._matching_engine = matching_engine
        self._fetch_limit = max(1, fetch_limit)
        self._max_results = max(1, max_results)
        self._logger = get_logger(__name__)

    async def search(self, query: SearchQuery) -> SearchResponse:
        resolved_sources = list(query.sources)
        providers = _resolve_providers(resolved_sources)
        gateway_query = GatewaySearchQuery(
            text=query.query,
            artist=None,
            limit=self._fetch_limit,
        )

        started = perf_counter()
        try:
            response = await self._integration.search_providers(
                providers, gateway_query
            )
        except ServiceError as exc:
            duration_ms = int((perf_counter() - started) * 1000)
            sources_value = ",".join(source.value for source in resolved_sources)
            log_event(
                self._logger,
                "service.call",
                component="service.search",
                operation="search",
                status="error",
                duration_ms=duration_ms,
                sources=sources_value,
                error=str(exc.api_error.error.code),
            )
            raise

        candidates, failures = _collect_candidates(
            response, query.query, self._matching_engine
        )

        candidates.sort(key=lambda item: item.score or 0.0, reverse=True)
        capped = candidates[: self._max_results]
        offset = min(query.offset, len(capped))
        limit = min(query.limit, self._max_results)
        page_slice = capped[offset : offset + limit]

        items = [item for item in page_slice]
        paging = Paging(limit=limit, offset=offset, total=len(capped))

        duration_ms = int((perf_counter() - started) * 1000)
        sources_value = ",".join(source.value for source in resolved_sources)
        failure_keys = ",".join(sorted(failures.keys()))
        log_event(
            self._logger,
            "service.call",
            component="service.search",
            operation="search",
            status=response.status,
            duration_ms=duration_ms,
            sources=sources_value,
            total_candidates=len(candidates),
            page_count=len(items),
            failures=failure_keys,
        )

        return SearchResponse(
            items=items,
            paging=paging,
            sources=resolved_sources,
            status=response.status,
            failures=failures,
        )


def _resolve_providers(sources: Iterable[SourceEnum]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for source in sources:
        provider = _SOURCE_TO_PROVIDER.get(source)
        if not provider:
            continue
        if provider in seen:
            continue
        resolved.append(provider)
        seen.add(provider)
    return resolved


def _collect_candidates(
    response,
    query_text: str,
    matching_engine: MatchingEngineProtocol,
) -> tuple[list[SearchItem], dict[str, str]]:
    results: list[SearchItem] = []
    failures: dict[str, str] = {}
    for result in response.results:
        source = _PROVIDER_TO_SOURCE.get(result.provider.lower())
        if source is None:
            continue
        if result.error is not None:
            api_error = to_api_error(result.error, provider=result.provider)
            failures[source.value] = api_error.error.message
            continue
        for track in result.tracks:
            item = _track_to_search_item(track, source, query_text, matching_engine)
            results.append(item)
    return results, failures


def _track_to_search_item(
    track: GatewayProviderTrack,
    source: SourceEnum,
    query_text: str,
    matching_engine: MatchingEngineProtocol,
) -> SearchItem:
    artists = [artist.name for artist in track.artists if artist.name]
    album_name = track.album.name if track.album else None
    metadata = _merge_metadata(track)
    score = matching_engine.compute_relevance_score(
        query_text,
        {
            "type": "track",
            "title": track.name,
            "album": album_name,
            "artists": artists,
            "source": source.value,
            "metadata": metadata,
        },
    )
    year = _extract_int(metadata, "year", "release_year")
    if year is None and track.album is not None:
        year = _extract_int(track.album.metadata, "year", "release_year")
    bitrate = _extract_int(metadata, "bitrate_kbps", "bitrate")
    genres = _collect_genres(metadata, track.album.metadata if track.album else None)
    identifier = track.id or f"{track.provider}:{track.name}"
    primary_artist = artists[0] if artists else None
    return SearchItem(
        type="track",
        id=identifier,
        source=source,
        title=track.name,
        artist=primary_artist,
        album=album_name,
        year=year,
        genres=genres,
        bitrate=bitrate,
        score=round(score, 4) if score is not None else None,
        metadata=metadata,
    )


def _merge_metadata(track: GatewayProviderTrack) -> dict[str, object]:
    payload = _sanitise_mapping(track.metadata)
    payload.setdefault("provider", track.provider)
    if track.id is not None:
        payload.setdefault("provider_track_id", track.id)
    if track.isrc:
        payload.setdefault("isrc", track.isrc)
    if track.duration_ms is not None:
        payload.setdefault("duration_ms", track.duration_ms)
    payload.setdefault("candidate_count", len(getattr(track, "candidates", []) or ()))
    if track.album is not None:
        album_meta = _sanitise_mapping(track.album.metadata)
        for key, value in album_meta.items():
            payload.setdefault(f"album_{key}", value)
    return payload


def _sanitise_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in mapping.items():
        cleaned[str(key)] = _sanitise_value(value)
    return cleaned


def _sanitise_value(value: object) -> object:
    if isinstance(value, _JSON_PRIMITIVES):
        return value
    if isinstance(value, Mapping):
        return _sanitise_mapping(value)
    if isinstance(value, (list, tuple, set)):
        return [_sanitise_value(item) for item in value]
    return str(value)


def _extract_int(mapping: Mapping[str, object], *keys: str) -> int | None:
    for key in keys:
        if key not in mapping:
            continue
        value = mapping[key]
        if isinstance(value, bool):  # pragma: no cover - defensive
            continue
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(str(value))
        except (TypeError, ValueError):
            continue
    return None


def _collect_genres(*mappings: Mapping[str, object] | None) -> list[str]:
    genres: list[str] = []
    seen: set[str] = set()
    for mapping in mappings:
        if not mapping:
            continue
        raw = mapping.get("genres")
        if isinstance(raw, (list, tuple, set)):
            for value in raw:
                text = str(value).strip()
                lowered = text.lower()
                if text and lowered not in seen:
                    genres.append(text)
                    seen.add(lowered)
    return genres


__all__ = ["SearchService"]
