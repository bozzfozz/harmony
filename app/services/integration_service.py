"""High level orchestration across configured music providers."""

from __future__ import annotations

from typing import Iterable, Sequence

from app.errors import DependencyError, ValidationAppError
from app.integrations.base import TrackCandidate
from app.integrations.contracts import ProviderTrack, SearchQuery, TrackProvider
from app.integrations.errors import to_application_error
from app.integrations.health import IntegrationHealth, ProviderHealthMonitor
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayConfig,
    ProviderGatewayError,
    ProviderGatewaySearchResponse,
)
from app.integrations.registry import ProviderRegistry


class IntegrationService:
    """Expose high level operations across configured music providers."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        gateway: ProviderGateway | None = None,
    ) -> None:
        self._registry = registry
        self._registry.initialise()
        initialise = getattr(self._registry, "initialise", None)
        if gateway is None:
            if callable(initialise):
                initialise()
            providers = self._registry.track_providers()
            config: ProviderGatewayConfig = self._registry.gateway_config
            self._gateway = ProviderGateway(providers=providers, config=config)
        else:
            self._gateway = gateway
            if callable(initialise):
                try:
                    initialise()
                except TypeError:
                    pass
        self._health_monitor = ProviderHealthMonitor(self._registry)

    async def search_tracks(
        self,
        provider: str,
        query: str,
        *,
        artist: str | None = None,
        limit: int = 50,
    ) -> list[TrackCandidate]:
        normalized_provider = provider.strip().lower()
        if not normalized_provider:
            raise ValidationAppError("provider must not be empty.")

        trimmed_query = query.strip()
        if not trimmed_query:
            raise ValidationAppError("query must not be empty.")
        if len(trimmed_query) > 256:
            raise ValidationAppError("query must not exceed 256 characters.")

        if limit <= 0:
            raise ValidationAppError("limit must be greater than zero.")
        clamped_limit = min(limit, 100)

        normalized_artist = artist.strip() if artist and artist.strip() else None

        try:
            self._registry.get_track_provider(normalized_provider)
        except KeyError as exc:
            raise ValidationAppError(f"provider '{provider}' is not enabled.") from exc

        query_model = SearchQuery(text=trimmed_query, artist=normalized_artist, limit=clamped_limit)

        try:
            tracks = await self._gateway.search_tracks(normalized_provider, query_model)
        except ProviderGatewayError as exc:
            mapped = to_application_error(provider, exc)
            raise mapped from exc

        return self._flatten_candidates(tracks)

    async def search_providers(
        self, providers: Sequence[str], query: SearchQuery
    ) -> ProviderGatewaySearchResponse:
        normalized: list[str] = []
        seen: set[str] = set()
        for provider in providers:
            normalized_name = provider.strip().lower()
            if not normalized_name:
                raise ValidationAppError("provider must not be empty.")
            if normalized_name in seen:
                continue
            try:
                self._registry.get_track_provider(normalized_name)
            except KeyError as exc:
                raise DependencyError("Requested search source is not available") from exc
            normalized.append(normalized_name)
            seen.add(normalized_name)

        return await self._gateway.search_many(normalized, query)

    def providers(self) -> Iterable[TrackProvider]:
        return self._registry.track_providers().values()

    async def health(self) -> IntegrationHealth:
        return await self._health_monitor.check_all()

    @staticmethod
    def _flatten_candidates(tracks: Iterable[ProviderTrack]) -> list[TrackCandidate]:
        candidates: list[TrackCandidate] = []
        for track in tracks:
            candidates.extend(track.candidates)
        return candidates


__all__ = ["IntegrationService"]
