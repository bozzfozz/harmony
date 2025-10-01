"""High level orchestration across configured music providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.errors import (
    DependencyError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ValidationAppError,
)
from app.integrations.base import TrackCandidate
from app.integrations.contracts import ProviderTrack, SearchQuery
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayConfig,
    ProviderGatewayDependencyError,
    ProviderGatewayError,
    ProviderGatewayInternalError,
    ProviderGatewayNotFoundError,
    ProviderGatewayRateLimitedError,
    ProviderGatewayTimeoutError,
    ProviderGatewayValidationError,
)
from app.integrations.registry import ProviderRegistry


@dataclass(slots=True)
class ProviderHealth:
    name: str
    enabled: bool
    health: str


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
        if gateway is None:
            providers = self._registry.track_providers()
            config: ProviderGatewayConfig = self._registry.gateway_config
            gateway = ProviderGateway(providers=providers, config=config)
        self._gateway = gateway

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
        except ProviderGatewayValidationError as exc:
            meta = {"provider_status": exc.status_code} if exc.status_code is not None else None
            raise ValidationAppError(f"{provider} rejected the search request.", meta=meta) from exc
        except ProviderGatewayRateLimitedError as exc:
            raise RateLimitedError(
                f"{provider} rate limited the search request.",
                retry_after_ms=exc.retry_after_ms,
                retry_after_header=exc.retry_after_header,
            ) from exc
        except ProviderGatewayNotFoundError as exc:
            raise NotFoundError(f"{provider} returned no matching results.") from exc
        except ProviderGatewayTimeoutError as exc:
            raise DependencyError(f"{provider} search timed out.") from exc
        except ProviderGatewayDependencyError as exc:
            meta = {"provider_status": exc.status_code} if exc.status_code is not None else None
            raise DependencyError(
                f"{provider} search is currently unavailable.", meta=meta
            ) from exc
        except ProviderGatewayInternalError as exc:
            raise InternalServerError(f"Failed to process {provider} search results.") from exc
        except ProviderGatewayError as exc:  # pragma: no cover - defensive guard
            raise InternalServerError(f"Unexpected error during {provider} search.") from exc

        return self._flatten_candidates(tracks)

    def providers(self) -> Iterable[object]:
        return self._registry.track_providers().values()

    def health(self) -> list[ProviderHealth]:
        status: list[ProviderHealth] = []
        enabled = set(self._registry.enabled_names)
        for name in enabled:
            try:
                provider = self._registry.get_track_provider(name)
            except KeyError:
                status.append(ProviderHealth(name=name, enabled=False, health="disabled"))
                continue
            status.append(ProviderHealth(name=provider.name, enabled=True, health="ok"))
        return status

    @staticmethod
    def _flatten_candidates(tracks: Iterable[ProviderTrack]) -> list[TrackCandidate]:
        candidates: list[TrackCandidate] = []
        for track in tracks:
            candidates.extend(track.candidates)
        return candidates


__all__ = ["IntegrationService", "ProviderHealth"]
