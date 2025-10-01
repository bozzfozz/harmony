from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pytest

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
    ProviderGatewayDependencyError,
    ProviderGatewayInternalError,
    ProviderGatewayNotFoundError,
    ProviderGatewayRateLimitedError,
    ProviderGatewaySearchResponse,
    ProviderGatewayTimeoutError,
    ProviderGatewayValidationError,
)
from app.services.integration_service import IntegrationService


@dataclass(slots=True)
class _StubTrackProvider:
    name: str


class _StubRegistry:
    def __init__(self, *, enabled: tuple[str, ...] = ("slskd",)) -> None:
        self.enabled_names = enabled
        self._providers = {name: _StubTrackProvider(name=name) for name in enabled}

    def initialise(self) -> None:  # pragma: no cover - trivial
        return None

    def get_track_provider(self, name: str) -> _StubTrackProvider:
        normalized = name.lower()
        if normalized not in self._providers:
            raise KeyError(name)
        return self._providers[normalized]

    def track_providers(
        self,
    ) -> dict[str, _StubTrackProvider]:  # pragma: no cover - unused by tests
        return dict(self._providers)

    @property
    def gateway_config(self):  # pragma: no cover - unused when injecting gateway
        raise AssertionError("gateway_config should not be accessed in tests")


class _StubGateway:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[tuple[str, SearchQuery]] = []

    async def search_tracks(self, provider: str, query: SearchQuery):
        self.calls.append((provider, query))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _StubGatewayMany:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], SearchQuery]] = []

    async def search_many(self, providers: Sequence[str], query: SearchQuery):
        self.calls.append((tuple(providers), query))
        return ProviderGatewaySearchResponse(results=())


def _make_candidate() -> TrackCandidate:
    return TrackCandidate(
        title="Song",
        artist="Artist",
        format="FLAC",
        bitrate_kbps=1000,
        size_bytes=1024,
        seeders=2,
        username="user",
        availability=0.5,
        source="slskd",
    )


@pytest.mark.asyncio
async def test_integration_service_delegates_to_gateway() -> None:
    candidate = _make_candidate()
    provider_track = ProviderTrack(name="Song", provider="slskd", candidates=(candidate,))
    gateway = _StubGateway([provider_track])
    registry = _StubRegistry()
    service = IntegrationService(registry=registry, gateway=gateway)  # type: ignore[arg-type]

    results = await service.search_tracks(
        "  slskd  ",
        "  Song  ",
        artist="  Artist  ",
        limit=250,
    )

    assert results == [candidate]
    assert gateway.calls[0][0] == "slskd"
    query = gateway.calls[0][1]
    assert query.text == "Song"
    assert query.artist == "Artist"
    assert query.limit == 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception, expected_error",
    [
        (
            ProviderGatewayValidationError("slskd", status_code=400, cause=None),
            ValidationAppError,
        ),
        (
            ProviderGatewayRateLimitedError(
                "slskd",
                retry_after_ms=10,
                retry_after_header="1",
                status_code=429,
                cause=None,
            ),
            RateLimitedError,
        ),
        (
            ProviderGatewayNotFoundError("slskd", status_code=404, cause=None),
            NotFoundError,
        ),
        (
            ProviderGatewayTimeoutError("slskd", timeout_ms=1000, cause=None),
            DependencyError,
        ),
        (
            ProviderGatewayDependencyError("slskd", status_code=502, cause=None),
            DependencyError,
        ),
        (
            ProviderGatewayInternalError("slskd", "boom"),
            InternalServerError,
        ),
    ],
)
async def test_integration_service_normalises_gateway_errors(
    exception: Exception, expected_error: type[Exception]
) -> None:
    registry = _StubRegistry()
    gateway = _StubGateway(exception)
    service = IntegrationService(registry=registry, gateway=gateway)  # type: ignore[arg-type]

    with pytest.raises(expected_error):
        await service.search_tracks("slskd", "query")


@pytest.mark.asyncio
async def test_search_providers_deduplicates_and_validates() -> None:
    registry = _StubRegistry(enabled=("spotify", "slskd"))
    gateway = _StubGatewayMany()
    service = IntegrationService(registry=registry, gateway=gateway)  # type: ignore[arg-type]

    query = SearchQuery(text="Song", artist=None, limit=10)
    response = await service.search_providers(["Spotify", "slskd", "spotify"], query)

    assert response.results == ()
    assert gateway.calls == [(("spotify", "slskd"), query)]


@pytest.mark.asyncio
async def test_search_providers_raises_dependency_error_for_unknown_provider() -> None:
    registry = _StubRegistry(enabled=("spotify",))
    gateway = _StubGatewayMany()
    service = IntegrationService(registry=registry, gateway=gateway)  # type: ignore[arg-type]

    query = SearchQuery(text="Song", artist=None, limit=10)

    with pytest.raises(DependencyError):
        await service.search_providers(["slskd"], query)
