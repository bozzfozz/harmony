from __future__ import annotations

import httpx
import pytest

from app.errors import DependencyError, InternalServerError, RateLimitedError, ValidationAppError
from app.integrations.slskd_adapter import (
    SlskdAdapter,
    SlskdAdapterDependencyError,
    SlskdAdapterInternalError,
    SlskdAdapterRateLimitedError,
)
from app.integrations.slskd_client import SlskdHttpClient
from app.schemas.music import Track
from app.services.integration_service import IntegrationService


@pytest.mark.asyncio
async def test_slskd_adapter_normalises_payload() -> None:
    payload = {
        "results": [
            {
                "username": "collector",
                "files": [
                    {
                        "id": "abc123",
                        "title": "Smells Like Teen Spirit",
                        "artist": "Nirvana",
                        "album": "Nevermind",
                        "duration": 301,
                        "bitrate": 320,
                        "size": 12_345_678,
                        "path": "\\\\collector\\music\\nirvana.flac",
                        "score": 0.92,
                    }
                ],
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v0/search/tracks"
        assert request.url.params["query"] == "nirvana"
        assert request.url.params["limit"] == "2"
        assert request.headers["X-API-Key"] == "secret"
        return httpx.Response(200, json=payload)

    adapter = SlskdAdapter(
        client=SlskdHttpClient(
            base_url="http://slskd.local",
            api_key="secret",
            transport=httpx.MockTransport(handler),
        ),
        timeout_ms=1200,
        rate_limit_fallback_ms=2500,
    )

    tracks = await adapter.search_tracks("nirvana", limit=2)

    assert len(tracks) == 1
    track = tracks[0]
    assert track["title"] == "Smells Like Teen Spirit"
    assert track["artists"] == ["Nirvana"]
    assert track["album"] == "Nevermind"
    assert track["duration_s"] == 301
    assert track["bitrate_kbps"] == 320
    assert track["size_bytes"] == 12_345_678
    assert track["magnet_or_path"] == "\\\\collector\\music\\nirvana.flac"
    assert track["source"] == "slskd"
    assert track["external_id"] == "abc123"
    assert track["score"] == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_slskd_adapter_caps_limit_at_50() -> None:
    seen_limit: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_limit.append(request.url.params["limit"])
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": str(index), "title": f"Song {index}", "artist": "Artist"}
                    for index in range(60)
                ]
            },
        )

    adapter = SlskdAdapter(
        client=SlskdHttpClient(
            base_url="http://slskd.local",
            transport=httpx.MockTransport(handler),
        ),
        timeout_ms=1200,
        rate_limit_fallback_ms=2000,
    )

    tracks = await adapter.search_tracks("query", limit=100)

    assert seen_limit == ["50"]
    assert len(tracks) == 50


@pytest.mark.asyncio
async def test_slskd_adapter_raises_rate_limited_with_retry_header() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "3"})

    adapter = SlskdAdapter(
        client=SlskdHttpClient(
            base_url="http://slskd.local",
            transport=httpx.MockTransport(handler),
        ),
        timeout_ms=1200,
        rate_limit_fallback_ms=2000,
    )

    with pytest.raises(SlskdAdapterRateLimitedError) as excinfo:
        await adapter.search_tracks("query")

    error = excinfo.value
    assert error.retry_after_ms == 3000
    assert error.retry_after_header == "3"


@pytest.mark.asyncio
async def test_slskd_adapter_rate_limit_fallback_without_header() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    adapter = SlskdAdapter(
        client=SlskdHttpClient(
            base_url="http://slskd.local",
            transport=httpx.MockTransport(handler),
        ),
        timeout_ms=1200,
        rate_limit_fallback_ms=1750,
    )

    with pytest.raises(SlskdAdapterRateLimitedError) as excinfo:
        await adapter.search_tracks("query")

    assert excinfo.value.retry_after_ms == 1750
    assert excinfo.value.retry_after_header is None


@pytest.mark.asyncio
async def test_slskd_adapter_translates_dependency_failures() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    adapter = SlskdAdapter(
        client=SlskdHttpClient(
            base_url="http://slskd.local",
            transport=httpx.MockTransport(handler),
        ),
        timeout_ms=1200,
        rate_limit_fallback_ms=2000,
    )

    with pytest.raises(SlskdAdapterDependencyError):
        await adapter.search_tracks("query")


@pytest.mark.asyncio
async def test_slskd_adapter_invalid_json_raises_internal_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="not-json")

    adapter = SlskdAdapter(
        client=SlskdHttpClient(
            base_url="http://slskd.local",
            transport=httpx.MockTransport(handler),
        ),
        timeout_ms=1200,
        rate_limit_fallback_ms=2000,
    )

    with pytest.raises(SlskdAdapterInternalError):
        await adapter.search_tracks("query")


class _StubRegistry:
    def __init__(self, adapter: object | None) -> None:
        self._adapter = adapter
        self.enabled_names = ("slskd",) if adapter else ()

    def initialise(self) -> None:  # pragma: no cover - test helper
        return None

    def get(self, name: str) -> object:
        if self._adapter is None or name != "slskd":
            raise KeyError(name)
        return self._adapter

    def all(self) -> list[object]:  # pragma: no cover - required by service
        return [self._adapter] if self._adapter else []


class _SuccessfulAdapter:
    name = "slskd"

    def __init__(self, response: list[Track]):
        self._response = response
        self.query: str | None = None
        self.limit: int | None = None

    async def search_tracks(self, query: str, *, limit: int = 20, timeout_ms: int | None = None):
        self.query = query
        self.limit = limit
        return self._response


@pytest.mark.asyncio
async def test_integration_service_returns_tracks() -> None:
    response = [
        {
            "title": "Song",
            "artists": ["Artist"],
            "source": "slskd",
            "external_id": "1",
        }
    ]
    adapter = _SuccessfulAdapter(response)
    service = IntegrationService(registry=_StubRegistry(adapter))

    tracks = await service.search_tracks("  query  ", limit=5)

    assert tracks == response
    assert adapter.query == "query"
    assert adapter.limit == 5


@pytest.mark.asyncio
async def test_integration_service_validates_input() -> None:
    service = IntegrationService(registry=_StubRegistry(_SuccessfulAdapter([])))

    with pytest.raises(ValidationAppError):
        await service.search_tracks("   ")
    with pytest.raises(ValidationAppError):
        await service.search_tracks("q" * 257)
    with pytest.raises(ValidationAppError):
        await service.search_tracks("ok", limit=0)


@pytest.mark.asyncio
async def test_integration_service_maps_rate_limit_error() -> None:
    class _RateLimitedAdapter:
        name = "slskd"

        async def search_tracks(
            self, query: str, *, limit: int = 20, timeout_ms: int | None = None
        ):
            raise SlskdAdapterRateLimitedError(
                headers={"Retry-After": "4"}, fallback_retry_after_ms=1000
            )

    service = IntegrationService(registry=_StubRegistry(_RateLimitedAdapter()))

    with pytest.raises(RateLimitedError) as excinfo:
        await service.search_tracks("query")

    assert excinfo.value.meta == {"retry_after_ms": 4000}


@pytest.mark.asyncio
async def test_integration_service_maps_dependency_error() -> None:
    class _FailingAdapter:
        name = "slskd"

        async def search_tracks(
            self, query: str, *, limit: int = 20, timeout_ms: int | None = None
        ):
            raise SlskdAdapterDependencyError("boom", status_code=504)

    service = IntegrationService(registry=_StubRegistry(_FailingAdapter()))

    with pytest.raises(DependencyError) as excinfo:
        await service.search_tracks("query")

    assert excinfo.value.meta == {"provider_status": 504}


@pytest.mark.asyncio
async def test_integration_service_maps_internal_error() -> None:
    class _BrokenAdapter:
        name = "slskd"

        async def search_tracks(
            self, query: str, *, limit: int = 20, timeout_ms: int | None = None
        ):
            raise SlskdAdapterInternalError("boom")

    service = IntegrationService(registry=_StubRegistry(_BrokenAdapter()))

    with pytest.raises(InternalServerError):
        await service.search_tracks("query")


@pytest.mark.asyncio
async def test_integration_service_handles_disabled_provider() -> None:
    service = IntegrationService(registry=_StubRegistry(None))

    with pytest.raises(DependencyError):
        await service.search_tracks("query")
