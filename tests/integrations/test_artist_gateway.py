from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.integrations.artist_gateway import ArtistGateway
from app.integrations.contracts import ProviderTrack, SearchQuery
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewaySearchResponse,
    ProviderGatewaySearchResult,
    ProviderGatewayTimeoutError,
)


def _search_response(*results: ProviderGatewaySearchResult) -> ProviderGatewaySearchResponse:
    return ProviderGatewaySearchResponse(results=results)


@pytest.mark.asyncio
async def test_fetch_artist_normalises_payload() -> None:
    provider_gateway = AsyncMock(spec=ProviderGateway)
    provider_gateway.search_many.return_value = _search_response(
        ProviderGatewaySearchResult(
            provider="spotify",
            tracks=(
                ProviderTrack(
                    name="Test Track",
                    provider="spotify",
                    metadata={
                        "artist": {
                            "id": "artist-1",
                            "etag": "artist-etag",
                            "fetched_at": "2024-01-01T12:00:00Z",
                            "provider_cursor": "artist-cursor",
                            "metadata": {"name": "Test Artist"},
                        },
                        "releases": [
                            {
                                "id": "release-1",
                                "etag": "release-etag",
                                "fetched_at": "2024-01-02T08:30:00Z",
                                "provider_cursor": "release-cursor",
                                "metadata": {"name": "Test Release"},
                            }
                        ],
                    },
                ),
            ),
        ),
    )

    gateway = ArtistGateway(provider_gateway=provider_gateway)
    response = await gateway.fetch_artist("artist-1", providers=("spotify",), limit=20)

    provider_gateway.search_many.assert_awaited_once()
    args, _ = provider_gateway.search_many.call_args
    assert args[0] == ("spotify",)
    assert isinstance(args[1], SearchQuery)
    assert args[1].text == "artist-1"
    assert args[1].limit == 20

    assert response.artist_id == "artist-1"
    assert len(response.results) == 1

    result = response.results[0]
    assert result.provider == "spotify"
    assert result.error is None
    assert result.retryable is False
    assert result.artist is not None
    assert result.artist.id == "artist-1"
    assert result.artist.etag == "artist-etag"
    assert result.artist.provider_cursor == "artist-cursor"
    assert result.artist.fetched_at == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert result.artist.metadata == {"name": "Test Artist"}
    assert len(result.releases) == 1

    release = result.releases[0]
    assert release.id == "release-1"
    assert release.etag == "release-etag"
    assert release.provider_cursor == "release-cursor"
    assert release.fetched_at == datetime(2024, 1, 2, 8, 30, tzinfo=timezone.utc)
    assert release.metadata == {"name": "Test Release"}
    assert response.releases == result.releases


@pytest.mark.asyncio
async def test_fetch_artist_records_retryable_error() -> None:
    error = ProviderGatewayTimeoutError("spotify", timeout_ms=5000)
    provider_gateway = AsyncMock(spec=ProviderGateway)
    provider_gateway.search_many.return_value = _search_response(
        ProviderGatewaySearchResult(
            provider="spotify",
            tracks=tuple(),
            error=error,
        )
    )

    gateway = ArtistGateway(provider_gateway=provider_gateway)
    response = await gateway.fetch_artist("artist-1", providers=("spotify",), limit=5)

    result = response.results[0]
    assert result.error is error
    assert result.retryable is True
    assert result.artist is None
    assert result.releases == ()
    assert response.errors == {"spotify": error}
    assert response.retryable is True
    assert response.releases == ()


@pytest.mark.asyncio
async def test_fetch_artist_deduplicates_releases() -> None:
    provider_gateway = AsyncMock(spec=ProviderGateway)
    provider_gateway.search_many.return_value = _search_response(
        ProviderGatewaySearchResult(
            provider="spotify",
            tracks=(
                ProviderTrack(
                    name="",
                    provider="spotify",
                    metadata={
                        "release": {
                            "id": "release-1",
                            "etag": "etag-1",
                            "metadata": {"name": "First"},
                        }
                    },
                ),
            ),
        ),
        ProviderGatewaySearchResult(
            provider="slskd",
            tracks=(
                ProviderTrack(
                    name="",
                    provider="slskd",
                    metadata={
                        "releases": [
                            {
                                "id": "release-1",
                                "etag": "etag-override",
                                "metadata": {"name": "Override"},
                            },
                            {
                                "id": "release-2",
                                "etag": "etag-2",
                                "metadata": {"name": "Second"},
                            },
                        ]
                    },
                ),
            ),
        ),
    )

    gateway = ArtistGateway(provider_gateway=provider_gateway)
    response = await gateway.fetch_artist("artist-1", providers=("spotify", "slskd"), limit=10)

    assert len(response.results) == 2
    aggregated = response.releases
    assert {release.id for release in aggregated} == {"release-1", "release-2"}

    release_map = {release.id: release for release in aggregated}
    assert release_map["release-1"].etag == "etag-override"
    assert release_map["release-1"].metadata == {"name": "Override"}
    assert release_map["release-2"].metadata == {"name": "Second"}
    assert response.retryable is False
