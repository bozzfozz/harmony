from __future__ import annotations

import importlib
from typing import Any

from app.api import search as search_module
from app.dependencies import (
    get_integration_service as dependency_integration_service,
    get_matching_engine as dependency_matching_engine,
)
from app.integrations.contracts import ProviderAlbum, ProviderArtist, ProviderTrack
from app.integrations.provider_gateway import (
    ProviderGatewaySearchResponse,
    ProviderGatewaySearchResult,
)
from app.main import app
from tests.simple_client import SimpleTestClient


class _StubMatchingEngine:
    def compute_relevance_score(self, query: str, payload: dict[str, Any]) -> float:
        return 1.0


class _StubIntegrationService:
    async def search_providers(self, providers, query):
        results: list[ProviderGatewaySearchResult] = []
        for name in providers:
            track = ProviderTrack(
                name="Example Track",
                provider=name,
                id=f"{name}-track",
                artists=(ProviderArtist(name="Example Artist"),),
                album=ProviderAlbum(name="Example Album"),
            )
            results.append(ProviderGatewaySearchResult(provider=name, tracks=(track,)))
        return ProviderGatewaySearchResponse(results=tuple(results))


def test_search_endpoint_emits_logging(monkeypatch) -> None:
    captured: list[tuple[str, dict[str, Any]]] = []

    def _capture(logger, event_name: str, /, **payload: Any) -> None:
        captured.append((event_name, payload))

    monkeypatch.setattr(search_module, "_log_event", _capture)
    monkeypatch.setattr("app.routers.search_router.log_event", _capture, raising=False)
    monkeypatch.setattr("app.logging_events.log_event", _capture)

    def _record_event(*args: Any, **kwargs: Any) -> None:
        _capture(args[0], args[1], **kwargs)

    monkeypatch.setattr(search_module, "_emit_api_event", _record_event)

    overrides = {
        dependency_matching_engine: lambda: _StubMatchingEngine(),
        dependency_integration_service: lambda: _StubIntegrationService(),
    }
    app.dependency_overrides.update(overrides)
    try:
        with SimpleTestClient(app) as client:
            response = client.post(
                "/api/v1/search",
                json={"query": "Example", "limit": 5, "offset": 0},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["items"], "expected at least one search result"
    finally:
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)

    assert captured, "expected api.request log event"
    event_name, payload = captured[-1]
    assert event_name == "api.request"
    assert payload["component"] == "router.search"
    assert payload["status"] == "ok"
    assert payload["method"] == "POST"
    assert payload["path"].endswith("/api/v1/search")


def test_search_max_limit_env_validation(monkeypatch) -> None:
    """Invalid environment overrides should fall back to the default limit."""

    global search_module

    monkeypatch.setenv("SEARCH_MAX_LIMIT", "-10")
    search_module = importlib.reload(search_module)

    try:
        assert search_module.SEARCH_MAX_LIMIT == 100
        assert search_module._resolve_search_max_limit() == 100
    finally:
        monkeypatch.delenv("SEARCH_MAX_LIMIT", raising=False)
        search_module = importlib.reload(search_module)
