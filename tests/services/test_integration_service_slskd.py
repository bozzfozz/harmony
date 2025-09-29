from __future__ import annotations

import types
from typing import Any

import httpx
import pytest

from app.errors import (
    DependencyError,
    InternalServerError,
    NotFoundError,
    RateLimitedError,
    ValidationAppError,
)
from app.integrations.slskd_adapter import (
    SlskdAdapter,
    SlskdAdapterDependencyError,
    SlskdAdapterInternalError,
    SlskdAdapterNotFoundError,
    SlskdAdapterRateLimitedError,
    SlskdAdapterValidationError,
)
from app.services.integration_service import IntegrationService


class StubRegistry:
    def __init__(self, adapter: SlskdAdapter) -> None:
        self._adapter = adapter

    @property
    def enabled_names(self) -> tuple[str, ...]:
        return ("slskd",)

    def initialise(self) -> None:
        return None

    def get(self, name: str) -> SlskdAdapter:
        if name.lower() != "slskd":
            raise KeyError(name)
        return self._adapter

    def all(self) -> tuple[SlskdAdapter, ...]:
        return (self._adapter,)


def _make_adapter(
    handler: httpx.MockTransport, **overrides: Any
) -> tuple[SlskdAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(base_url="http://slskd", transport=handler)
    adapter = SlskdAdapter(
        base_url="http://slskd",
        api_key="token",
        timeout_ms=overrides.get("timeout_ms", 2000),
        max_retries=overrides.get("max_retries", 1),
        backoff_base_ms=overrides.get("backoff_base_ms", 5),
        jitter_pct=overrides.get("jitter_pct", 0),
        preferred_formats=overrides.get("preferred_formats", ("FLAC", "MP3")),
        max_results=overrides.get("max_results", 25),
        client=client,
    )
    return adapter, client


@pytest.mark.asyncio
async def test_integration_service_dispatches_to_slskd_adapter() -> None:
    observed: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        observed["query"] = request.url.params["query"]
        observed["limit"] = request.url.params["limit"]
        payload = {
            "results": [
                {
                    "username": "user",
                    "files": [
                        {
                            "title": "Song",
                            "artist": "Artist",
                            "format": "FLAC",
                            "seeders": 2,
                        }
                    ],
                }
            ]
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    adapter, client = _make_adapter(transport, max_results=20)
    registry = StubRegistry(adapter)
    service = IntegrationService(registry=registry)

    try:
        results = await service.search_tracks(
            "slskd",
            "  Song  (clean)  ",
            artist="  Artist  ",
            limit=60,
        )
    finally:
        await client.aclose()

    assert observed["query"] == "Artist - Song"
    assert observed["limit"] == "20"
    assert len(results) == 1
    assert results[0].source == "slskd"
    assert results[0].title == "Song"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception, expected_error",
    [
        (SlskdAdapterValidationError("bad", status_code=400), ValidationAppError),
        (SlskdAdapterRateLimitedError(headers={}, fallback_retry_after_ms=50), RateLimitedError),
        (SlskdAdapterNotFoundError("missing", status_code=404), NotFoundError),
        (SlskdAdapterDependencyError("down", status_code=502), DependencyError),
        (SlskdAdapterInternalError("oops"), InternalServerError),
    ],
)
async def test_integration_service_propagates_error_contract(
    exception: Exception, expected_error: type[Exception]
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP handler should not be invoked")

    transport = httpx.MockTransport(handler)
    adapter, client = _make_adapter(transport)
    registry = StubRegistry(adapter)
    service = IntegrationService(registry=registry)

    async def raiser(
        self: SlskdAdapter, *args: Any, **kwargs: Any
    ) -> Any:  # pragma: no cover - patched
        raise exception

    adapter.search_tracks = types.MethodType(raiser, adapter)

    try:
        with pytest.raises(expected_error):
            await service.search_tracks("slskd", "query")
    finally:
        await client.aclose()
