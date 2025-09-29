from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.integrations.base import TrackCandidate
from app.integrations.slskd_adapter import (
    SlskdAdapter,
    SlskdAdapterDependencyError,
    SlskdAdapterNotFoundError,
    SlskdAdapterRateLimitedError,
    SlskdAdapterValidationError,
)


def _build_adapter(
    handler: httpx.MockTransport, **overrides: Any
) -> tuple[SlskdAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        base_url=overrides.get("base_url", "http://slskd"),
        transport=handler,
    )
    adapter = SlskdAdapter(
        base_url=overrides.get("base_url", "http://slskd"),
        api_key=overrides.get("api_key", "secret"),
        timeout_ms=overrides.get("timeout_ms", 2_000),
        max_retries=overrides.get("max_retries", 2),
        backoff_base_ms=overrides.get("backoff_base_ms", 10),
        jitter_pct=overrides.get("jitter_pct", 0),
        preferred_formats=overrides.get("preferred_formats", ("FLAC", "MP3", "AAC")),
        max_results=overrides.get("max_results", 10),
        client=client,
    )
    return adapter, client


@pytest.mark.asyncio
async def test_search_tracks_returns_iterable_list() -> None:
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
                        }
                    ],
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport)

    try:
        results = await adapter.search_tracks(" Song A  ", artist="Artist", limit=5)
    finally:
        await client.aclose()

    assert isinstance(results, list)
    assert all(isinstance(candidate, TrackCandidate) for candidate in results)
    assert results[0].download_uri == "magnet:?xt=urn:btih:flac"


@pytest.mark.asyncio
async def test_retries_then_success_logs_attempts_and_durations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(503)
        payload = {
            "results": [
                {
                    "files": [
                        {
                            "title": "Recovery",
                            "artist": "Tester",
                            "format": "MP3",
                            "seeders": 5,
                        }
                    ]
                }
            ]
        }
        return httpx.Response(200, json=payload)

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("app.integrations.slskd_adapter.asyncio.sleep", fake_sleep)
    attempt_logs: list[dict[str, Any]] = []
    complete_logs: list[dict[str, Any]] = []

    def capture_attempt(self: SlskdAdapter, **payload: Any) -> None:
        attempt_logs.append(payload)

    def capture_complete(self: SlskdAdapter, **payload: Any) -> None:
        complete_logs.append(payload)

    monkeypatch.setattr(SlskdAdapter, "_log_attempt", capture_attempt)
    monkeypatch.setattr(SlskdAdapter, "_log_complete", capture_complete)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, max_retries=2, backoff_base_ms=25, jitter_pct=0)

    try:
        results = await adapter.search_tracks("Recovery", artist="Tester", limit=3)
    finally:
        await client.aclose()

    assert len(results) == 1
    assert len(sleep_calls) == 1
    assert [entry["attempt"] for entry in attempt_logs] == [1, 2]
    assert all(entry["duration_ms"] >= 0 for entry in attempt_logs)
    assert complete_logs[-1]["status"] == "ok"
    assert complete_logs[-1]["retries_used"] == 1


@pytest.mark.asyncio
async def test_timeout_exhaustion_maps_dependency_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout", request=request)

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("app.integrations.slskd_adapter.asyncio.sleep", fake_sleep)
    complete_logs: list[dict[str, Any]] = []

    def capture_complete(self: SlskdAdapter, **payload: Any) -> None:
        complete_logs.append(payload)

    monkeypatch.setattr(SlskdAdapter, "_log_complete", capture_complete)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, max_retries=1, backoff_base_ms=10, jitter_pct=0)

    try:
        with pytest.raises(SlskdAdapterDependencyError):
            await adapter.search_tracks("Timeout City")
    finally:
        await client.aclose()

    assert complete_logs[-1]["status"] == "error"
    assert complete_logs[-1]["error"] in {"exhausted", "SlskdAdapterDependencyError"}


@pytest.mark.asyncio
async def test_404_maps_not_found() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, max_retries=0)

    try:
        with pytest.raises(SlskdAdapterNotFoundError):
            await adapter.search_tracks("missing")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_rate_limited_error_exposes_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"})

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("app.integrations.slskd_adapter.asyncio.sleep", fake_sleep)
    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, max_retries=1, backoff_base_ms=50, jitter_pct=0)

    try:
        with pytest.raises(SlskdAdapterRateLimitedError) as excinfo:
            await adapter.search_tracks("limited")
    finally:
        await client.aclose()

    assert excinfo.value.retry_after_ms >= 0


def test_missing_config_fails_fast() -> None:
    with pytest.raises(RuntimeError):
        SlskdAdapter(
            base_url=" ",
            api_key="secret",
            timeout_ms=1_000,
            max_retries=1,
            backoff_base_ms=10,
            jitter_pct=0,
            preferred_formats=("FLAC",),
            max_results=5,
        )

    with pytest.raises(RuntimeError):
        SlskdAdapter(
            base_url="http://slskd",
            api_key=" ",
            timeout_ms=1_000,
            max_retries=1,
            backoff_base_ms=10,
            jitter_pct=0,
            preferred_formats=("FLAC",),
            max_results=5,
        )


@pytest.mark.asyncio
async def test_validation_error_bubbles_up_without_retry() -> None:
    attempt_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        attempt_count += 1
        return httpx.Response(400)

    transport = httpx.MockTransport(handler)
    adapter, client = _build_adapter(transport, max_retries=3)

    try:
        with pytest.raises(SlskdAdapterValidationError):
            await adapter.search_tracks("invalid")
    finally:
        await client.aclose()

    assert attempt_count == 1
