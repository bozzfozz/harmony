from __future__ import annotations

import random
from typing import Any

import httpx
import pytest

from app.integrations.slskd_adapter import (
    SlskdAdapter,
    SlskdAdapterDependencyError,
    SlskdAdapterRateLimitedError,
    SlskdAdapterValidationError,
)


def _build_adapter(
    handler: httpx.MockTransport, **overrides: Any
) -> tuple[SlskdAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(base_url="http://slskd", transport=handler)
    adapter = SlskdAdapter(
        base_url="http://slskd",
        api_key="secret",
        timeout_ms=overrides.get("timeout_ms", 2000),
        max_retries=overrides.get("max_retries", 2),
        backoff_base_ms=overrides.get("backoff_base_ms", 5),
        preferred_formats=overrides.get("preferred_formats", ("FLAC", "MP3", "AAC")),
        max_results=overrides.get("max_results", 10),
        client=client,
    )
    return adapter, client


@pytest.mark.asyncio
async def test_search_tracks_success_maps_results_sorted_by_preferred_formats() -> None:
    captured_queries: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_queries.append(request.url.params["query"])
        payload = {
            "results": [
                {
                    "username": "collector-flac",
                    "files": [
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "format": "FLAC",
                            "bitrate": 0,
                            "size_bytes": 1234,
                            "seeders": 12,
                            "magnet": "magnet:?xt=urn:btih:flac",
                        },
                        {
                            "title": "Song A",
                            "artist": "Artist",
                            "format": "MP3",
                            "bitrate_kbps": 320,
                            "size": 4321,
                            "seeders": 3,
                        },
                    ],
                },
                {
                    "username": "another-user",
                    "files": [
                        {
                            "filename": "song_a.ogg",
                            "bitrate": 256,
                            "size_bytes": 2222,
                            "seeders": 1,
                        }
                    ],
                },
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, preferred_formats=("FLAC", "MP3", "OGG"))

    try:
        results = await adapter.search_tracks("Song A (Explicit)", artist="Artist feat. B", limit=5)
    finally:
        await client.aclose()

    assert captured_queries[0] == "Artist - Song A"
    assert [candidate.format for candidate in results] == ["FLAC", "MP3", "OGG"]
    assert results[0].username == "collector-flac"
    assert results[0].download_uri == "magnet:?xt=urn:btih:flac"
    assert results[0].availability == 1.0
    assert results[1].bitrate_kbps == 320
    assert results[2].format == "OGG"


@pytest.mark.asyncio
async def test_search_tracks_timeout_then_retry_success() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.TimeoutException("timeout", request=request)
        payload = {
            "results": [
                {
                    "username": "retry-user",
                    "files": [
                        {
                            "title": "Resilient",
                            "artist": "Tester",
                            "format": "FLAC",
                            "seeders": 4,
                        }
                    ],
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, max_retries=1, backoff_base_ms=1)

    try:
        results = await adapter.search_tracks("Resilient", artist="Tester", limit=2)
    finally:
        await client.aclose()

    assert attempts == 2
    assert results[0].username == "retry-user"


@pytest.mark.asyncio
async def test_search_tracks_429_rate_limited_after_retries() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={})

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, max_retries=1, backoff_base_ms=10)

    random.seed(0)
    try:
        with pytest.raises(SlskdAdapterRateLimitedError) as excinfo:
            await adapter.search_tracks("Blocked", artist="Artist")
    finally:
        await client.aclose()

    assert excinfo.value.retry_after_ms >= 0


@pytest.mark.asyncio
async def test_search_tracks_5xx_retry_then_fail_dependency_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, max_retries=1, backoff_base_ms=1)

    try:
        with pytest.raises(SlskdAdapterDependencyError) as excinfo:
            await adapter.search_tracks("Server Down")
    finally:
        await client.aclose()

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_search_tracks_4xx_validation_error_no_retry() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, max_retries=3)

    try:
        with pytest.raises(SlskdAdapterValidationError):
            await adapter.search_tracks("Invalid")
    finally:
        await client.aclose()

    assert attempts == 1


@pytest.mark.asyncio
async def test_search_tracks_mapping_unknown_fields_defaults() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "results": [
                {
                    "files": [
                        {
                            "name": "Mystery",
                            "artist": None,
                            "size": None,
                            "user": "mystery-user",
                            "count": 0,
                        }
                    ]
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, preferred_formats=("FLAC",))

    try:
        results = await adapter.search_tracks("Mystery")
    finally:
        await client.aclose()

    candidate = results[0]
    assert candidate.artist is None
    assert candidate.format is None
    assert candidate.size_bytes is None
    assert candidate.seeders == 0
    assert candidate.availability == 0.0
    assert candidate.metadata == {}
