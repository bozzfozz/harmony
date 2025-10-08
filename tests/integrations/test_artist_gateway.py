from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.integrations.artist_gateway import ArtistGateway
from app.integrations.contracts import ProviderArtist, ProviderRelease
from app.integrations.provider_gateway import (ProviderGateway,
                                               ProviderGatewayTimeoutError)


@pytest.mark.asyncio
async def test_fetch_artist_collects_provider_dtos() -> None:
    provider_gateway = AsyncMock(spec=ProviderGateway)
    provider_gateway.fetch_artist.return_value = ProviderArtist(
        source="spotify",
        source_id="artist-1",
        name="Test Artist",
        genres=("rock",),
    )
    provider_gateway.fetch_artist_releases.return_value = [
        ProviderRelease(
            source="spotify",
            source_id="release-1",
            artist_source_id="artist-1",
            title="Test Release",
            type="album",
        )
    ]

    gateway = ArtistGateway(provider_gateway=provider_gateway)
    response = await gateway.fetch_artist("artist-1", providers=("spotify",), limit=20)

    provider_gateway.fetch_artist.assert_awaited_once_with(
        "spotify", artist_id="artist-1", name="artist-1"
    )
    provider_gateway.fetch_artist_releases.assert_awaited_once_with("spotify", "artist-1", limit=20)

    assert response.artist_id == "artist-1"
    assert len(response.results) == 1

    result = response.results[0]
    assert result.provider == "spotify"
    assert result.error is None
    assert result.retryable is False
    assert result.artist is not None
    assert result.artist.name == "Test Artist"
    assert result.artist.genres == ("rock",)
    assert len(result.releases) == 1
    assert result.releases[0].title == "Test Release"
    assert response.releases == result.releases


@pytest.mark.asyncio
async def test_fetch_artist_records_retryable_error() -> None:
    provider_gateway = AsyncMock(spec=ProviderGateway)
    provider_gateway.fetch_artist.side_effect = ProviderGatewayTimeoutError(
        "spotify", timeout_ms=5000
    )

    gateway = ArtistGateway(provider_gateway=provider_gateway)
    response = await gateway.fetch_artist("artist-1", providers=("spotify",), limit=5)

    provider_gateway.fetch_artist.assert_awaited_once()
    provider_gateway.fetch_artist_releases.assert_not_awaited()

    result = response.results[0]
    assert isinstance(result.error, ProviderGatewayTimeoutError)
    assert result.retryable is True
    assert result.artist is None
    assert result.releases == ()
    assert response.errors == {result.provider: result.error}
    assert response.retryable is True
    assert response.releases == ()


@pytest.mark.asyncio
async def test_fetch_artist_deduplicates_releases_by_identifier() -> None:
    provider_gateway = AsyncMock(spec=ProviderGateway)
    provider_gateway.fetch_artist.side_effect = [
        ProviderArtist(source="spotify", source_id="artist-1", name="Artist"),
        ProviderArtist(source="slskd", source_id="artist-1", name="Artist"),
    ]
    provider_gateway.fetch_artist_releases.side_effect = [
        [
            ProviderRelease(
                source="spotify",
                source_id="release-1",
                artist_source_id="artist-1",
                title="First",
                type="album",
            )
        ],
        [
            ProviderRelease(
                source="slskd",
                source_id="release-1",
                artist_source_id="artist-1",
                title="Override",
                type="album",
            ),
            ProviderRelease(
                source="slskd",
                source_id="release-2",
                artist_source_id="artist-1",
                title="Second",
                type="album",
            ),
        ],
    ]

    gateway = ArtistGateway(provider_gateway=provider_gateway)
    response = await gateway.fetch_artist("artist-1", providers=("spotify", "slskd"), limit=10)

    assert len(response.results) == 2
    aggregated = response.releases
    assert {release.source_id for release in aggregated} == {"release-1", "release-2"}

    release_map = {release.source_id: release for release in aggregated}
    assert release_map["release-1"].title == "Override"
    assert release_map["release-2"].title == "Second"
    assert response.retryable is False
