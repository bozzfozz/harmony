"""Service orchestrating calls across configured music providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.errors import DependencyError, InternalServerError, RateLimitedError, ValidationAppError
from app.integrations.base import TrackCandidate
from app.integrations.slskd_adapter import (
    SlskdAdapter,
    SlskdAdapterDependencyError,
    SlskdAdapterInternalError,
    SlskdAdapterRateLimitedError,
    SlskdAdapterValidationError,
)
from app.integrations.registry import ProviderRegistry


@dataclass(slots=True)
class ProviderHealth:
    name: str
    enabled: bool
    health: str


class IntegrationService:
    """Expose high level operations across configured music providers."""

    def __init__(self, *, registry: ProviderRegistry) -> None:
        self._registry = registry
        self._registry.initialise()

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
            resolved = self._registry.get(normalized_provider)
        except KeyError as exc:
            raise ValidationAppError(f"provider '{provider}' is not enabled.") from exc

        if not isinstance(resolved, SlskdAdapter):
            raise DependencyError("Requested provider does not support track search.")

        effective_limit = min(clamped_limit, resolved.max_results)

        try:
            return await resolved.search_tracks(
                trimmed_query,
                artist=normalized_artist,
                limit=effective_limit,
            )
        except SlskdAdapterValidationError as exc:
            meta = {"provider_status": exc.status_code} if exc.status_code is not None else None
            raise ValidationAppError("slskd rejected the search request.", meta=meta) from exc
        except SlskdAdapterRateLimitedError as exc:
            raise RateLimitedError(
                "slskd rate limited the search request.",
                retry_after_ms=exc.retry_after_ms,
                retry_after_header=exc.retry_after_header,
            ) from exc
        except SlskdAdapterDependencyError as exc:
            meta = {"provider_status": exc.status_code} if exc.status_code is not None else None
            raise DependencyError("slskd search is currently unavailable.", meta=meta) from exc
        except SlskdAdapterInternalError as exc:
            raise InternalServerError("Failed to process slskd search results.") from exc
        except Exception as exc:  # pragma: no cover - defensive fallback
            raise InternalServerError("Unexpected error during slskd search.") from exc

    def providers(self) -> Iterable[object]:
        return self._registry.all()

    def health(self) -> list[ProviderHealth]:
        status: list[ProviderHealth] = []
        enabled = set(self._registry.enabled_names)
        for name in enabled:
            try:
                provider = self._registry.get(name)
            except KeyError:
                status.append(ProviderHealth(name=name, enabled=False, health="disabled"))
                continue
            status.append(ProviderHealth(name=provider.name, enabled=True, health="ok"))
        return status
