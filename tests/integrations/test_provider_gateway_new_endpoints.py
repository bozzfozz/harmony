import pytest

from app.integrations.contracts import (
    ProviderAlbumDetails,
    ProviderArtist,
    ProviderNotFoundError,
    ProviderRelease,
    ProviderTimeoutError,
    ProviderTrack,
    SearchQuery,
)
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayConfig,
    ProviderGatewayNotFoundError,
    ProviderGatewayTimeoutError,
    ProviderRetryPolicy,
)


class _StubProvider:
    def __init__(self) -> None:
        self.name = "stub"

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        return []

    async def fetch_artist(
        self, *, artist_id: str | None = None, name: str | None = None
    ) -> ProviderArtist | None:
        return None

    async def fetch_artist_releases(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderRelease]:
        return []

    async def fetch_album(self, album_source_id: str) -> ProviderAlbumDetails:
        raise ProviderTimeoutError(self.name, 1000)

    async def fetch_artist_top_tracks(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderTrack]:
        raise ProviderNotFoundError(self.name, "missing", status_code=404)


def _gateway(provider: _StubProvider) -> ProviderGateway:
    policy = ProviderRetryPolicy(
        timeout_ms=10,
        retry_max=0,
        backoff_base_ms=10,
        jitter_pct=0.0,
    )
    config = ProviderGatewayConfig(
        max_concurrency=1,
        default_policy=policy,
        provider_policies={"stub": policy},
    )
    return ProviderGateway(providers={"stub": provider}, config=config)


@pytest.mark.asyncio
async def test_fetch_album_timeout_maps_to_gateway_error() -> None:
    gateway = _gateway(_StubProvider())

    with pytest.raises(ProviderGatewayTimeoutError):
        await gateway.fetch_album("stub", "album-1")


@pytest.mark.asyncio
async def test_fetch_artist_top_tracks_maps_not_found() -> None:
    gateway = _gateway(_StubProvider())

    with pytest.raises(ProviderGatewayNotFoundError):
        await gateway.fetch_artist_top_tracks("stub", "artist-1")
