from __future__ import annotations

import pytest

from app.integrations.contracts import ProviderArtist, ProviderRelease, ProviderTrack, SearchQuery
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayConfig,
    ProviderRetryPolicy,
)


class DummyProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.artist_calls: list[tuple[str | None, str | None]] = []
        self.release_calls: list[tuple[str, int | None]] = []

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        return []

    async def fetch_artist(
        self, *, artist_id: str | None = None, name: str | None = None
    ) -> ProviderArtist:
        self.artist_calls.append((artist_id, name))
        identifier = artist_id or name or "unknown"
        return ProviderArtist(
            source=self.name,
            source_id=identifier,
            name=f"{self.name.title()} Artist",
        )

    async def fetch_artist_releases(
        self, artist_source_id: str, *, limit: int | None = None
    ) -> list[ProviderRelease]:
        self.release_calls.append((artist_source_id, limit))
        return [
            ProviderRelease(
                source=self.name,
                source_id=f"{artist_source_id}-{self.name}-1",
                artist_source_id=artist_source_id,
                title=f"{self.name.title()} Release",
                type="album",
            )
        ]


@pytest.mark.asyncio
async def test_gateway_returns_uniform_dtos_for_all_providers() -> None:
    config = ProviderGatewayConfig(
        max_concurrency=2,
        default_policy=ProviderRetryPolicy(
            timeout_ms=1000,
            retry_max=0,
            backoff_base_ms=50,
            jitter_pct=0.0,
        ),
        provider_policies={},
    )
    spotify = DummyProvider("spotify")
    slskd = DummyProvider("slskd")
    gateway = ProviderGateway(providers={"spotify": spotify, "slskd": slskd}, config=config)

    spotify_artist = await gateway.fetch_artist("spotify", artist_id="artist-1")
    spotify_releases = await gateway.fetch_artist_releases("spotify", "artist-1", limit=5)
    slskd_artist = await gateway.fetch_artist("slskd", artist_id="artist-1")
    slskd_releases = await gateway.fetch_artist_releases("slskd", "artist-1")

    assert spotify_artist.source == "spotify"
    assert spotify_artist.name == "Spotify Artist"
    assert spotify_releases[0].source == "spotify"
    assert slskd_artist.source == "slskd"
    assert slskd_releases[0].source == "slskd"

    assert spotify.artist_calls == [("artist-1", None)]
    assert slskd.artist_calls == [("artist-1", None)]
    assert spotify.release_calls == [("artist-1", 5)]
    assert slskd.release_calls == [("artist-1", None)]
