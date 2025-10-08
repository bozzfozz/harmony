from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.integrations.contracts import (
    ProviderAlbum,
    ProviderAlbumDetails,
    ProviderDependencyError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderTrack,
    ProviderValidationError,
    SearchQuery,
)
from app.integrations.slskd_adapter import SlskdAdapter


def _build_adapter(
    handler: httpx.MockTransport, **overrides: Any
) -> tuple[SlskdAdapter, httpx.AsyncClient]:
    base_url = overrides.get("base_url", "http://slskd")
    client = httpx.AsyncClient(base_url=base_url, transport=handler)
    adapter = SlskdAdapter(
        base_url=base_url,
        api_key=overrides.get("api_key", "secret"),
        timeout_ms=overrides.get("timeout_ms", 2_000),
        preferred_formats=overrides.get("preferred_formats", ("FLAC", "MP3")),
        max_results=overrides.get("max_results", 10),
        client=client,
    )
    return adapter, client


@pytest.mark.asyncio
async def test_search_tracks_returns_provider_tracks() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v0/search/tracks"
        payload = {
            "results": [
                {
                    "username": "collector",
                    "files": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "format": "FLAC",
                            "seeders": 3,
                            "magnet": "magnet:?xt=urn:btih:flac",
                            "score": 0.9,
                        }
                    ],
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport)

    try:
        tracks = await adapter.search_tracks(SearchQuery(text="Song A", artist="Artist", limit=5))
    finally:
        await client.aclose()

    assert isinstance(tracks, list)
    assert all(isinstance(track, ProviderTrack) for track in tracks)
    assert tracks[0].candidates
    assert tracks[0].score == 0.9


@pytest.mark.asyncio
async def test_adapter_raises_validation_error_on_bad_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400)

    adapter, client = _build_adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderValidationError):
            await adapter.search_tracks(SearchQuery(text=" ", artist=None, limit=1))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_adapter_raises_rate_limited_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"})

    adapter, client = _build_adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderRateLimitedError) as excinfo:
            await adapter.search_tracks(SearchQuery(text="Song", artist=None, limit=1))
    finally:
        await client.aclose()

    assert excinfo.value.retry_after_header == "1"


@pytest.mark.asyncio
async def test_adapter_raises_not_found_when_no_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    adapter, client = _build_adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderNotFoundError):
            await adapter.search_tracks(SearchQuery(text="Song", artist=None, limit=1))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_adapter_wraps_network_failures() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("boom")

    adapter, client = _build_adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderTimeoutError):
            await adapter.search_tracks(SearchQuery(text="Song", artist=None, limit=1))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_adapter_maps_server_errors_to_dependency_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    adapter, client = _build_adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderDependencyError):
            await adapter.search_tracks(SearchQuery(text="Song", artist=None, limit=1))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_fetch_artist_top_tracks_limits_results(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, client = _build_adapter(
        httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )

    tracks = [
        ProviderTrack(name="First", provider="slskd"),
        ProviderTrack(name="Second", provider="slskd"),
    ]

    async def _fake_search(query: SearchQuery) -> list[ProviderTrack]:
        return tracks

    monkeypatch.setattr(adapter, "search_tracks", _fake_search)

    try:
        results = await adapter.fetch_artist_top_tracks("artist-1", limit=1)
    finally:
        await client.aclose()

    assert [track.name for track in results] == ["First"]


@pytest.mark.asyncio
async def test_fetch_album_builds_details_from_tracks(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, client = _build_adapter(
        httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )

    track = ProviderTrack(
        name="Song",
        provider="slskd",
        album=ProviderAlbum(name="Collected", id="album-1"),
        metadata={"genre": "metal", "year": 2000},
    )

    async def _fake_search(query: SearchQuery) -> list[ProviderTrack]:
        return [track]

    monkeypatch.setattr(adapter, "search_tracks", _fake_search)

    try:
        details = await adapter.fetch_album("album-1")
    finally:
        await client.aclose()

    assert isinstance(details, ProviderAlbumDetails)
    assert details.album.name == "Collected"
    assert len(details.tracks) == 1
