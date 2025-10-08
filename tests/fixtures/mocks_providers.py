"""Provider gateway stubs tailored for artist workflow tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pytest

from app.integrations.artist_gateway import ArtistGatewayResponse, ArtistGatewayResult
from app.integrations.contracts import ProviderArtist, ProviderRelease
from app.integrations.provider_gateway import ProviderGatewayError
from app.orchestrator import providers as orchestrator_providers


@dataclass(slots=True)
class ArtistGatewayMock:
    """Record fetch calls and return preconfigured artist responses."""

    responses: dict[str, ArtistGatewayResponse]
    errors: dict[str, ProviderGatewayError]
    calls: list[dict[str, Any]]

    def __init__(self) -> None:
        self.responses = {}
        self.errors = {}
        self.calls = []

    def set_response(
        self,
        artist_id: str,
        *,
        provider: str,
        artist: ProviderArtist,
        releases: Sequence[ProviderRelease],
    ) -> ArtistGatewayResponse:
        """Register a successful gateway response for ``artist_id``."""

        response = ArtistGatewayResponse(
            artist_id=artist_id,
            results=(
                ArtistGatewayResult(
                    provider=provider,
                    artist=artist,
                    releases=tuple(releases),
                    error=None,
                    retryable=False,
                ),
            ),
        )
        self.responses[artist_id] = response
        self.errors.pop(artist_id, None)
        return response

    def set_error(self, artist_id: str, error: ProviderGatewayError) -> None:
        """Register an error to be raised for ``artist_id``."""

        self.errors[artist_id] = error
        self.responses.pop(artist_id, None)

    async def fetch_artist(
        self,
        artist_id: str,
        *,
        providers: Sequence[str],
        limit: int,
    ) -> ArtistGatewayResponse:
        self.calls.append(
            {
                "artist_id": artist_id,
                "providers": tuple(providers),
                "limit": int(limit),
            }
        )
        error = self.errors.get(artist_id)
        if error is not None:
            raise error
        return self.responses.get(artist_id, ArtistGatewayResponse(artist_id=artist_id, results=()))


@pytest.fixture
def artist_gateway_stub(monkeypatch: pytest.MonkeyPatch) -> ArtistGatewayMock:
    """Provide an artist gateway stub and ensure orchestrator uses it."""

    stub = ArtistGatewayMock()
    original_builder = orchestrator_providers.build_artist_sync_handler_deps

    def build_stubbed_deps(*args: Any, **kwargs: Any):
        deps = original_builder(*args, **kwargs)
        deps.gateway = stub
        return deps

    monkeypatch.setattr(
        orchestrator_providers,
        "build_artist_sync_handler_deps",
        build_stubbed_deps,
    )
    return stub
