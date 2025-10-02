from __future__ import annotations

import pytest

from app.integrations.base import TrackCandidate
from app.integrations.contracts import ProviderAlbum, ProviderArtist, ProviderTrack, SearchQuery
from app.integrations.provider_gateway import (
    ProviderGatewaySearchResponse,
    ProviderGatewaySearchResult,
    ProviderGatewayTimeoutError,
)
from app.services.errors import ServiceError
from app.services.integration_service import IntegrationService


class _StubProvider:
    def __init__(self, name: str) -> None:
        self.name = name


class _StubRegistry:
    def __init__(self) -> None:
        self._providers = {"spotify": _StubProvider("spotify")}
        self.initialised = False

    def initialise(self) -> None:
        self.initialised = True

    def track_providers(self) -> dict[str, _StubProvider]:
        return dict(self._providers)

    @property
    def gateway_config(self):  # pragma: no cover - not used when gateway injected
        raise AssertionError("gateway_config should not be accessed in this test")

    def get_track_provider(self, name: str) -> _StubProvider:
        normalized = name.lower()
        if normalized not in self._providers:
            raise KeyError(name)
        return self._providers[normalized]


class _StubGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def search_tracks(self, provider: str, query: SearchQuery) -> list[ProviderTrack]:
        self.calls.append(("tracks", (provider,)))
        return [
            ProviderTrack(
                name="Track",
                provider=provider,
                id="track-1",
                artists=(ProviderArtist(name="Artist"),),
                album=ProviderAlbum(name="Album"),
                candidates=(
                    TrackCandidate(
                        title="Track",
                        artist="Artist",
                        format="FLAC",
                        bitrate_kbps=320,
                        size_bytes=1024,
                        seeders=1,
                        username="demo",
                        availability=0.5,
                        source="soulseek",
                    ),
                ),
            )
        ]

    async def search_many(
        self, providers: tuple[str, ...], query: SearchQuery
    ) -> ProviderGatewaySearchResponse:
        self.calls.append(("many", tuple(sorted(providers))))
        track = ProviderTrack(
            name="Track",
            provider=providers[0],
            id="track-2",
            artists=(ProviderArtist(name="Artist"),),
        )
        result = ProviderGatewaySearchResult(provider=providers[0], tracks=(track,))
        return ProviderGatewaySearchResponse(results=(result,))


class _FailingGateway(_StubGateway):
    async def search_tracks(self, provider: str, query: SearchQuery) -> list[ProviderTrack]:
        raise ProviderGatewayTimeoutError(provider, timeout_ms=5000)


@pytest.mark.asyncio
async def test_search_tracks_delegates_to_gateway() -> None:
    gateway = _StubGateway()
    service = IntegrationService(registry=_StubRegistry(), gateway=gateway)

    candidates = await service.search_tracks("Spotify", "Example")

    assert gateway.calls == [("tracks", ("spotify",))]
    assert len(candidates) == 1
    assert isinstance(candidates[0], TrackCandidate)


@pytest.mark.asyncio
async def test_search_tracks_maps_gateway_error() -> None:
    service = IntegrationService(registry=_StubRegistry(), gateway=_FailingGateway())

    with pytest.raises(ServiceError) as captured:
        await service.search_tracks("spotify", "query")

    api_error = captured.value.api_error
    assert api_error.error.code == "DEPENDENCY_ERROR"
    assert api_error.error.details == {"provider": "spotify", "timeout_ms": 5000}


@pytest.mark.asyncio
async def test_search_providers_normalizes_and_deduplicates() -> None:
    gateway = _StubGateway()
    service = IntegrationService(registry=_StubRegistry(), gateway=gateway)
    query = SearchQuery(text="Song", artist=None, limit=10)

    response = await service.search_providers(["Spotify", "spotify", "SPOTIFY"], query)

    assert gateway.calls == [("many", ("spotify",))]
    assert response.results[0].provider == "spotify"


@pytest.mark.asyncio
async def test_search_providers_unknown_provider_raises_service_error() -> None:
    registry = _StubRegistry()
    registry._providers.clear()
    service = IntegrationService(registry=registry, gateway=_StubGateway())
    query = SearchQuery(text="Song", artist=None, limit=10)

    with pytest.raises(ServiceError) as captured:
        await service.search_providers(["unknown"], query)

    api_error = captured.value.api_error
    assert api_error.error.code == "DEPENDENCY_ERROR"
    assert api_error.error.details == {"provider": "unknown"}
