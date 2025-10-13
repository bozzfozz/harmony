"""Service layer protocol definitions for dependency injection."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.integrations.contracts import ProviderTrack, SearchQuery
from app.integrations.provider_gateway import ProviderGatewaySearchResponse


class ProviderGatewayProtocol(Protocol):
    """Protocol implemented by the provider gateway facade."""

    async def search_tracks(self, provider: str, query: SearchQuery) -> list[ProviderTrack]:
        """Execute a search against a single provider and return raw tracks."""

    async def search_many(
        self, providers: Sequence[str], query: SearchQuery
    ) -> ProviderGatewaySearchResponse:
        """Execute a search against multiple providers and return an aggregated response."""


class MatchingEngineProtocol(Protocol):
    """Protocol exposing the matching engine capabilities used by services."""

    def compute_relevance_score(self, query: str, payload: dict[str, object]) -> float:
        """Return a lightweight relevance score for a candidate payload."""
