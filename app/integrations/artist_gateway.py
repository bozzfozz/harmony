from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.integrations.contracts import ProviderArtist, ProviderRelease
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayDependencyError,
    ProviderGatewayError,
    ProviderGatewayRateLimitedError,
    ProviderGatewayTimeoutError,
)


@dataclass(slots=True, frozen=True)
class ArtistGatewayResult:
    """Container describing the outcome of a provider specific fetch."""

    provider: str
    artist: ProviderArtist | None
    releases: tuple[ProviderRelease, ...]
    error: ProviderGatewayError | None = None
    retryable: bool = False


@dataclass(slots=True, frozen=True)
class ArtistGatewayResponse:
    """Aggregated response for multi-provider artist fetch operations."""

    artist_id: str
    results: tuple[ArtistGatewayResult, ...]

    @property
    def releases(self) -> tuple[ProviderRelease, ...]:
        """Return the deduplicated set of releases across providers."""

        seen: dict[str, ProviderRelease] = {}
        for result in self.results:
            for release in result.releases:
                key = release.source_id or release.title
                if not key:
                    key = f"{release.source}:{release.title}"
                seen[key] = release
        return tuple(seen.values())

    @property
    def errors(self) -> Mapping[str, ProviderGatewayError]:
        return {
            result.provider: result.error for result in self.results if result.error is not None
        }

    @property
    def retryable(self) -> bool:
        return any(result.retryable for result in self.results if result.error)


class ArtistGateway:
    """Facade providing release lookups while reusing provider gateway policies."""

    def __init__(self, *, provider_gateway: ProviderGateway) -> None:
        self._provider_gateway = provider_gateway

    async def fetch_artist(
        self,
        artist_id: str,
        *,
        providers: Sequence[str],
        limit: int = 50,
    ) -> ArtistGatewayResponse:
        """Fetch artist releases from the configured providers."""

        effective_limit = max(1, int(limit))
        if not providers:
            return ArtistGatewayResponse(artist_id=artist_id, results=())

        async def _run(name: str) -> ArtistGatewayResult:
            return await self._fetch_from_provider(name, artist_id, effective_limit)

        tasks = [asyncio.create_task(_run(provider)) for provider in providers]
        results = await asyncio.gather(*tasks)
        return ArtistGatewayResponse(artist_id=artist_id, results=tuple(results))

    async def _fetch_from_provider(
        self, provider: str, artist_identifier: str, limit: int
    ) -> ArtistGatewayResult:
        provider_label = provider
        try:
            artist = await self._provider_gateway.fetch_artist(
                provider,
                artist_id=artist_identifier,
                name=artist_identifier,
            )
        except ProviderGatewayError as error:
            return ArtistGatewayResult(
                provider=provider_label,
                artist=None,
                releases=tuple(),
                error=error,
                retryable=self._is_retryable(error),
            )

        if artist is not None and artist.source:
            provider_label = artist.source

        error: ProviderGatewayError | None = None
        releases: tuple[ProviderRelease, ...] = ()
        if artist is not None:
            release_identifier = artist.source_id or artist_identifier
            if release_identifier:
                try:
                    release_list = await self._provider_gateway.fetch_artist_releases(
                        provider,
                        release_identifier,
                        limit=limit,
                    )
                except ProviderGatewayError as release_error:
                    error = release_error
                else:
                    releases = tuple(release_list)

        return ArtistGatewayResult(
            provider=provider_label,
            artist=artist,
            releases=releases,
            error=error,
            retryable=self._is_retryable(error),
        )

    @staticmethod
    def _is_retryable(error: ProviderGatewayError | None) -> bool:
        if error is None:
            return False
        return isinstance(
            error,
            (
                ProviderGatewayTimeoutError
                | ProviderGatewayRateLimitedError
                | ProviderGatewayDependencyError
            ),
        )


__all__ = [
    "ArtistGateway",
    "ArtistGatewayResponse",
    "ArtistGatewayResult",
]
