from __future__ import annotations

import pytest

from app.integrations.contracts import ProviderAlbum, ProviderArtist, ProviderTrack
from app.integrations.provider_gateway import (
    ProviderGatewaySearchResponse,
    ProviderGatewaySearchResult,
    ProviderGatewayTimeoutError,
)
from app.schemas.common import SourceEnum
from app.schemas.search import SearchQuery
from app.services.search_service import SearchService


class _StubMatchingEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def compute_relevance_score(self, query: str, payload: dict[str, object]) -> float:
        self.calls.append((query, payload))
        return 0.75


class _StubIntegrationService:
    def __init__(self, response: ProviderGatewaySearchResponse) -> None:
        self.response = response
        self.calls: list[tuple[tuple[str, ...], object]] = []

    async def search_providers(self, providers, query):
        self.calls.append((tuple(providers), query))
        return self.response


@pytest.mark.asyncio
async def test_search_service_builds_response_and_scores() -> None:
    track = ProviderTrack(
        name="Example Track",
        provider="spotify",
        id="track-1",
        artists=(ProviderArtist(source="spotify", name="Example Artist"),),
        album=ProviderAlbum(name="Example Album"),
        metadata={"bitrate_kbps": 320, "genres": ["rock"]},
    )
    result_ok = ProviderGatewaySearchResult(provider="spotify", tracks=(track,))
    result_failed = ProviderGatewaySearchResult(
        provider="slskd",
        tracks=tuple(),
        error=ProviderGatewayTimeoutError("slskd", timeout_ms=2000),
    )
    response = ProviderGatewaySearchResponse(results=(result_ok, result_failed))
    matching = _StubMatchingEngine()
    integration = _StubIntegrationService(response)
    service = SearchService(integration_service=integration, matching_engine=matching)

    query = SearchQuery(query="Example", limit=5, offset=0)
    result = await service.search(query)

    assert integration.calls
    providers, gateway_query = integration.calls[0]
    assert providers == ("spotify", "slskd")
    assert gateway_query.text == "Example"

    assert result.status == "partial"
    assert result.paging.total == 1
    assert result.items[0].source == SourceEnum.SPOTIFY
    assert result.items[0].score == pytest.approx(0.75, rel=1e-3)
    assert result.failures == {"soulseek": "slskd timed out after 2000ms"}
    assert matching.calls
