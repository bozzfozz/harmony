from __future__ import annotations

import pytest

from app.config import _parse_enabled_providers, _parse_provider_timeouts
from app.integrations.contracts import TrackProvider
from app.services.integration_service import IntegrationService


def test_parse_enabled_providers_deduplicates_and_normalises() -> None:
    result = _parse_enabled_providers("Spotify, Plex, spotify \n slskd")
    assert result == ("spotify", "plex", "slskd")


def test_parse_provider_timeouts_reads_env_values() -> None:
    result = _parse_provider_timeouts(
        {
            "SPOTIFY_TIMEOUT_MS": "2000",
            "PLEX_TIMEOUT_MS": "3000",
            "SLSKD_TIMEOUT_MS": "not-a-number",
        }
    )
    assert result["spotify"] == 2000
    assert result["plex"] == 3000
    assert result["slskd"] == 8000


class _StubProvider(TrackProvider):
    name = "stub"

    async def search_tracks(self, query):  # pragma: no cover - unused here
        return []

    async def check_health(self):  # pragma: no cover - simple stub
        return {"status": "ok"}


class _StubRegistry:
    def __init__(self, providers: dict[str, TrackProvider]) -> None:
        self._providers = providers
        self.enabled_names = tuple(providers.keys())

    def initialise(self) -> None:  # pragma: no cover - trivial setup
        return None

    def get_track_provider(self, name: str) -> TrackProvider:
        return self._providers[name]

    def track_providers(self) -> dict[str, TrackProvider]:  # pragma: no cover - unused helper
        return dict(self._providers)

    @property
    def gateway_config(self):  # pragma: no cover - unused when injecting gateway
        raise AssertionError


class _NullGateway:
    async def search_tracks(self, provider: str, query):  # pragma: no cover - unused helper
        raise NotImplementedError


@pytest.mark.asyncio
async def test_integration_service_health_marks_enabled() -> None:
    registry = _StubRegistry({"stub": _StubProvider()})
    service = IntegrationService(registry=registry, gateway=_NullGateway())  # type: ignore[arg-type]

    report = await service.health()

    assert report.overall == "ok"
    assert report.providers[0].provider == "stub"
    assert report.providers[0].status == "ok"
