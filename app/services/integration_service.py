"""High level orchestration across configured music providers."""

from __future__ import annotations

from time import perf_counter
from typing import Iterable, Sequence

from app.integrations.base import TrackCandidate
from app.integrations.contracts import ProviderTrack, SearchQuery, TrackProvider
from app.integrations.health import IntegrationHealth, ProviderHealthMonitor
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayConfig,
    ProviderGatewaySearchResponse,
)
from app.integrations.registry import ProviderRegistry
from app.logging import get_logger
from app.logging_events import log_event
from app.schemas.errors import ApiError, ErrorCode
from app.services.errors import ServiceError, to_api_error
from app.services.types import ProviderGatewayProtocol


class IntegrationService:
    """Expose high level operations across configured music providers."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        gateway: ProviderGatewayProtocol | None = None,
    ) -> None:
        self._registry = registry
        # ``initialise`` can be a no-op for tests; call if present for backwards compat.
        initialise = getattr(self._registry, "initialise", None)
        if callable(initialise):
            initialise()
        providers = self._registry.track_providers()
        if gateway is None:
            config: ProviderGatewayConfig = self._registry.gateway_config
            self._gateway = ProviderGateway(providers=providers, config=config)
        else:
            self._gateway = gateway
        self._health_monitor = ProviderHealthMonitor(self._registry)
        self._logger = get_logger(__name__)

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
            raise ServiceError(
                ApiError.from_components(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="provider must not be empty.",
                )
            )

        trimmed_query = query.strip()
        if not trimmed_query:
            raise ServiceError(
                ApiError.from_components(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="query must not be empty.",
                )
            )
        if len(trimmed_query) > 256:
            raise ServiceError(
                ApiError.from_components(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="query must not exceed 256 characters.",
                )
            )

        if limit <= 0:
            raise ServiceError(
                ApiError.from_components(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="limit must be greater than zero.",
                )
            )
        clamped_limit = min(limit, 100)

        normalized_artist = artist.strip() if artist and artist.strip() else None

        try:
            self._registry.get_track_provider(normalized_provider)
        except KeyError as exc:
            raise ServiceError(
                ApiError.from_components(
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"provider '{provider}' is not enabled.",
                )
            ) from exc

        query_model = SearchQuery(text=trimmed_query, artist=normalized_artist, limit=clamped_limit)

        started = perf_counter()
        try:
            tracks = await self._gateway.search_tracks(normalized_provider, query_model)
        except Exception as exc:
            api_error = to_api_error(exc, provider=normalized_provider)
            duration_ms = int((perf_counter() - started) * 1000)
            log_event(
                self._logger,
                "service.call",
                component="service.integration",
                operation="search_tracks",
                status="error",
                provider=normalized_provider,
                duration_ms=duration_ms,
                error=exc.__class__.__name__,
            )
            raise ServiceError(api_error) from exc

        duration_ms = int((perf_counter() - started) * 1000)
        log_event(
            self._logger,
            "service.call",
            component="service.integration",
            operation="search_tracks",
            status="ok",
            provider=normalized_provider,
            duration_ms=duration_ms,
            result_count=len(tracks),
        )

        return self._flatten_candidates(tracks)

    async def search_providers(
        self, providers: Sequence[str], query: SearchQuery
    ) -> ProviderGatewaySearchResponse:
        normalized: list[str] = []
        seen: set[str] = set()
        for provider in providers:
            normalized_name = provider.strip().lower()
            if not normalized_name:
                raise ServiceError(
                    ApiError.from_components(
                        code=ErrorCode.VALIDATION_ERROR,
                        message="provider must not be empty.",
                    )
                )
            if normalized_name in seen:
                continue
            try:
                self._registry.get_track_provider(normalized_name)
            except KeyError as exc:
                raise ServiceError(
                    ApiError.from_components(
                        code=ErrorCode.DEPENDENCY_ERROR,
                        message="Requested search source is not available.",
                        details={"provider": provider},
                    )
                ) from exc
            normalized.append(normalized_name)
            seen.add(normalized_name)

        started = perf_counter()
        try:
            response = await self._gateway.search_many(normalized, query)
        except Exception as exc:
            api_error = to_api_error(exc)
            duration_ms = int((perf_counter() - started) * 1000)
            providers_value = ",".join(normalized)
            log_event(
                self._logger,
                "service.call",
                component="service.integration",
                operation="search_many",
                status="error",
                duration_ms=duration_ms,
                providers=providers_value,
                error=exc.__class__.__name__,
            )
            raise ServiceError(api_error) from exc

        duration_ms = int((perf_counter() - started) * 1000)
        providers_value = ",".join(normalized)
        total_tracks = sum(len(item.tracks) for item in response.results)
        log_event(
            self._logger,
            "service.call",
            component="service.integration",
            operation="search_many",
            status=response.status,
            duration_ms=duration_ms,
            providers=providers_value,
            result_count=total_tracks,
        )
        return response

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
