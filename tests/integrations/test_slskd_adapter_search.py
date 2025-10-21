"""Behavioural tests for :mod:`app.integrations.slskd_adapter`."""

from __future__ import annotations

from collections.abc import Sequence
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.integrations.contracts import (
    ProviderDependencyError,
    ProviderRateLimitedError,
    ProviderValidationError,
    SearchQuery,
)
from app.integrations.slskd_adapter import SlskdAdapter


def _build_adapter(
    client: Mock,
    *,
    preferred_formats: Sequence[str] | None = None,
    max_results: int = 5,
) -> SlskdAdapter:
    return SlskdAdapter(
        base_url="https://slskd.local",
        api_key="secret",
        timeout_ms=1_500,
        preferred_formats=preferred_formats or ("FLAC", "MP3"),
        max_results=max_results,
        client=client,
    )


@pytest.mark.asyncio
async def test_search_tracks_returns_ranked_results_and_normalizes_query() -> None:
    payload = {
        "results": [
            {
                "username": "crate-digger",
                "files": [
                    {
                        "title": "Song Title",
                        "artist": "Main Artist",
                        "format": "FLAC",
                        "bitrate": 900,
                        "size": 12_000_000,
                        "seeders": 1,
                        "download_uri": "magnet:?xt=urn:btih:flac",
                    },
                    {
                        "title": "Song Title",
                        "artist": "Main Artist",
                        "format": "MP3",
                        "bitrate": 320,
                        "size": 5_000_000,
                        "seeders": 10,
                        "download_uri": "magnet:?xt=urn:btih:mp3",
                    },
                    {
                        "title": "Song Title",
                        "artist": "Main Artist",
                        "format": "OGG",
                        "bitrate": 160,
                        "size": 4_000_000,
                        "seeders": 4,
                        "download_uri": "magnet:?xt=urn:btih:ogg",
                    },
                ],
            }
        ]
    }
    response = httpx.Response(httpx.codes.OK, json=payload)
    client = Mock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)
    client.aclose = AsyncMock()
    adapter = _build_adapter(client, max_results=2)

    query = SearchQuery(
        text="Song Title feat. Guest Artist",
        artist="Main Artist ft. Collaborator",
        limit=5,
    )

    results = await adapter.search_tracks(query)

    formats = [track.candidates[0].format for track in results]
    assert formats == ["FLAC", "MP3"]
    assert [track.name for track in results] == ["Song Title", "Song Title"]

    await_args = client.get.await_args
    assert await_args.args[0] == "/api/v0/search/tracks"
    params = await_args.kwargs["params"]
    assert params["query"] == "Main Artist Song Title"
    assert params["limit"] == 2
    headers = await_args.kwargs["headers"]
    assert headers["X-API-Key"] == "secret"


@pytest.mark.asyncio
async def test_search_tracks_raises_validation_error_for_http_400() -> None:
    response = httpx.Response(httpx.codes.BAD_REQUEST)
    client = Mock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)
    client.aclose = AsyncMock()
    adapter = _build_adapter(client)

    query = SearchQuery(text="query", artist=None, limit=1)

    with pytest.raises(ProviderValidationError) as excinfo:
        await adapter.search_tracks(query)

    assert excinfo.value.status_code == httpx.codes.BAD_REQUEST


@pytest.mark.asyncio
async def test_search_tracks_raises_rate_limited_error_with_retry_after() -> None:
    response = httpx.Response(
        httpx.codes.TOO_MANY_REQUESTS,
        headers={"Retry-After": "2"},
    )
    client = Mock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)
    client.aclose = AsyncMock()
    adapter = _build_adapter(client)

    query = SearchQuery(text="query", artist=None, limit=1)

    with pytest.raises(ProviderRateLimitedError) as excinfo:
        await adapter.search_tracks(query)

    error = excinfo.value
    assert error.status_code == httpx.codes.TOO_MANY_REQUESTS
    assert error.retry_after_header == "2"
    assert error.retry_after_ms == 2000


@pytest.mark.asyncio
async def test_search_tracks_wraps_transport_errors_as_dependency_error() -> None:
    client = Mock(spec=httpx.AsyncClient)
    client.get = AsyncMock(side_effect=httpx.HTTPError("boom"))
    client.aclose = AsyncMock()
    adapter = _build_adapter(client)

    query = SearchQuery(text="query", artist=None, limit=1)

    with pytest.raises(ProviderDependencyError) as excinfo:
        await adapter.search_tracks(query)

    assert isinstance(excinfo.value.cause, httpx.HTTPError)
