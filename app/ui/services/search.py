from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request

from app.api.search import smart_search
from app.core.matching_engine import MusicMatchingEngine
from app.dependencies import get_integration_service, get_matching_engine
from app.logging import get_logger
from app.schemas_search import SearchItem, SearchRequest
from app.services.integration_service import IntegrationService

logger = get_logger(__name__)


@dataclass(slots=True)
class SearchResultDownload:
    """Payload required to queue a download for a search result."""

    username: str
    files: tuple[Mapping[str, Any], ...]


@dataclass(slots=True)
class SearchResult:
    identifier: str
    title: str
    artist: str | None
    source: str
    score: float
    bitrate: int | None
    audio_format: str | None
    download: SearchResultDownload | None = None


@dataclass(slots=True)
class SearchResultsPage:
    items: Sequence[SearchResult]
    total: int
    limit: int
    offset: int


class SearchUiService:
    """Execute smart search queries for UI forms."""

    def __init__(
        self,
        matching_engine: MusicMatchingEngine,
        integration_service: IntegrationService,
    ) -> None:
        self._matching_engine = matching_engine
        self._integration_service = integration_service

    async def search(
        self,
        request: Request,
        *,
        query: str,
        limit: int,
        offset: int,
        sources: Sequence[str] | None = None,
    ) -> SearchResultsPage:
        payload = SearchRequest(
            query=query,
            limit=limit,
            offset=offset,
            sources=list(sources or []),
        )
        response = await smart_search(
            payload,
            request,
            matching_engine=self._matching_engine,
            service=self._integration_service,
        )
        rows = tuple(self._to_result(item) for item in response.items)
        logger.debug(
            "search.ui.results",
            extra={
                "query": query,
                "returned": len(rows),
                "total": response.total,
            },
        )
        return SearchResultsPage(
            items=rows,
            total=response.total,
            limit=response.limit,
            offset=response.offset,
        )

    @staticmethod
    def _to_result(item: SearchItem) -> SearchResult:
        payload = item.model_dump()
        download = SearchUiService._extract_download_payload(payload)
        return SearchResult(
            identifier=str(payload.get("id", "")),
            title=str(payload.get("title", "")),
            artist=payload.get("artist"),
            source=str(payload.get("source", "")),
            score=float(payload.get("score", 0.0)),
            bitrate=payload.get("bitrate"),
            audio_format=payload.get("format"),
            download=download,
        )

    @staticmethod
    def _extract_download_payload(payload: Mapping[str, Any]) -> SearchResultDownload | None:
        metadata = payload.get("metadata")
        if not isinstance(metadata, Mapping):
            return None
        candidate = metadata.get("candidate")
        if not isinstance(candidate, Mapping):
            return None

        raw_username = candidate.get("username")
        username = str(raw_username).strip() if raw_username else ""
        download_uri = candidate.get("download_uri")
        if not username or not download_uri:
            return None

        candidate_metadata = candidate.get("metadata")
        filename: str | None = None
        if isinstance(candidate_metadata, Mapping):
            metadata_filename = candidate_metadata.get("filename")
            if metadata_filename:
                filename = str(metadata_filename).strip() or None

        if not filename:
            title = str(candidate.get("title") or "").strip()
            artist = str(candidate.get("artist") or "").strip()
            if artist and title:
                filename = f"{artist} - {title}"
            elif title:
                filename = title

        if not filename:
            fallback = str(payload.get("title") or "").strip()
            filename = fallback or None

        filename = filename or "download"
        normalised_source = str(payload.get("source") or "").strip()

        file_payload: dict[str, Any] = {
            "filename": filename,
            "name": filename,
            "download_uri": str(download_uri),
            "source": f"ui-search:{normalised_source}" if normalised_source else "ui-search",
        }

        for key in ("format", "bitrate_kbps", "size_bytes", "seeders"):
            value = candidate.get(key)
            if value is not None:
                file_payload[key] = value

        extra_metadata: dict[str, Any] = {
            "search_identifier": payload.get("id"),
            "search_source": normalised_source,
        }
        title = str(payload.get("title") or "").strip()
        artist = str(payload.get("artist") or "").strip()
        if title:
            extra_metadata["search_title"] = title
        if artist:
            extra_metadata["search_artist"] = artist
        if isinstance(candidate_metadata, Mapping):
            path_value = candidate_metadata.get("path") or candidate_metadata.get("filename")
            if path_value:
                extra_metadata["candidate_path"] = path_value

        file_payload["metadata"] = extra_metadata

        return SearchResultDownload(username=username, files=(file_payload,))


def get_search_ui_service(
    matching_engine: MusicMatchingEngine = Depends(get_matching_engine),
    integration_service: IntegrationService = Depends(get_integration_service),
) -> SearchUiService:
    return SearchUiService(matching_engine, integration_service)


__all__ = [
    "SearchResultDownload",
    "SearchResult",
    "SearchResultsPage",
    "SearchUiService",
    "get_search_ui_service",
]
