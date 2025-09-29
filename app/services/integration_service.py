"""Service orchestrating calls across configured music providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, cast

from app.errors import DependencyError, InternalServerError, RateLimitedError, ValidationAppError
from app.integrations.base import MusicProvider
from app.integrations.slskd_adapter import (
    SlskdAdapter,
    SlskdAdapterDependencyError,
    SlskdAdapterInternalError,
    SlskdAdapterRateLimitedError,
)
from app.integrations.registry import ProviderRegistry
from app.schemas.music import Track as IntegrationTrack


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

    async def search_tracks(self, query: str, limit: int = 20) -> list[IntegrationTrack]:
        trimmed = query.strip()
        if not trimmed:
            raise ValidationAppError("query must not be empty.")
        if len(trimmed) > 256:
            raise ValidationAppError("query must not exceed 256 characters.")
        if limit <= 0:
            raise ValidationAppError("limit must be greater than zero.")

        try:
            provider = self._registry.get("slskd")
        except KeyError as exc:
            raise DependencyError("slskd integration is not enabled.") from exc

        adapter = cast(SlskdAdapter, provider)
        effective_limit = min(limit, 50)

        try:
            return await adapter.search_tracks(trimmed, limit=effective_limit)
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

    def providers(self) -> Iterable[MusicProvider]:
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
