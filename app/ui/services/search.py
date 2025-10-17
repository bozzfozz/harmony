from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import Depends, Request

from app.api.search import smart_search
from app.core.matching_engine import MusicMatchingEngine
from app.dependencies import get_integration_service, get_matching_engine
from app.logging import get_logger
from app.schemas_search import SearchItem, SearchRequest
from app.services.integration_service import IntegrationService

logger = get_logger(__name__)


@dataclass(slots=True)
class SearchResult:
    identifier: str
    title: str
    artist: str | None
    source: str
    score: float
    bitrate: int | None
    audio_format: str | None


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
        return SearchResult(
            identifier=str(payload.get("id", "")),
            title=str(payload.get("title", "")),
            artist=payload.get("artist"),
            source=str(payload.get("source", "")),
            score=float(payload.get("score", 0.0)),
            bitrate=payload.get("bitrate"),
            audio_format=payload.get("format"),
        )


def get_search_ui_service(
    matching_engine: MusicMatchingEngine = Depends(get_matching_engine),
    integration_service: IntegrationService = Depends(get_integration_service),
) -> SearchUiService:
    return SearchUiService(matching_engine, integration_service)


__all__ = [
    "SearchResult",
    "SearchResultsPage",
    "SearchUiService",
    "get_search_ui_service",
]
