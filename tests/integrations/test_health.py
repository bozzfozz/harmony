from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from app.integrations.contracts import ProviderTrack, SearchQuery, TrackProvider
from app.integrations.health import IntegrationHealth, ProviderHealthMonitor


@dataclass
class _StubProvider(TrackProvider):
    name: str
    health_payload: Any

    async def search_tracks(self, query: SearchQuery) -> list[ProviderTrack]:
        return []

    async def check_health(self) -> Any:
        await asyncio.sleep(0)
        return self.health_payload


class _RegistryStub:
    def __init__(self, providers: Mapping[str, TrackProvider]):
        self._providers = dict(providers)

    @property
    def enabled_names(self) -> tuple[str, ...]:
        return tuple(self._providers.keys())

    def track_providers(self) -> Mapping[str, TrackProvider]:
        return dict(self._providers)

    def get_track_provider(self, name: str) -> TrackProvider:
        return self._providers[name]


@pytest.mark.asyncio
async def test_provider_health_monitor_reports_status() -> None:
    providers = {
        "spotify": _StubProvider(name="spotify", health_payload={"status": "ok"}),
        "slskd": _StubProvider(name="slskd", health_payload={"status": "down"}),
    }
    monitor = ProviderHealthMonitor(_RegistryStub(providers))

    report = await monitor.check_provider("spotify")
    assert report.provider == "spotify"
    assert report.status == "ok"

    report_down = await monitor.check_provider("slskd")
    assert report_down.status == "down"


@pytest.mark.asyncio
async def test_integration_health_aggregates_overall_status() -> None:
    providers = {
        "spotify": _StubProvider(name="spotify", health_payload={"status": "ok"}),
        "slskd": _StubProvider(name="slskd", health_payload={"status": "degraded"}),
    }
    monitor = ProviderHealthMonitor(_RegistryStub(providers))

    aggregate: IntegrationHealth = await monitor.check_all()
    assert aggregate.overall == "degraded"
    assert {report.provider for report in aggregate.providers} == {"spotify", "slskd"}
