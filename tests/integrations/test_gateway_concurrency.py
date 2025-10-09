from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from app.integrations.contracts import ProviderTrack, SearchQuery
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayConfig,
    ProviderRetryPolicy,
)


@dataclass
class _Tracker:
    active: int = 0
    max_active: int = 0
    lock: asyncio.Lock = field(init=False, repr=False, default_factory=asyncio.Lock)

    async def enter(self) -> None:
        async with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    async def leave(self) -> None:
        async with self.lock:
            self.active -= 1


@dataclass
class _RecordingProvider:
    name: str
    tracker: _Tracker

    async def search_tracks(self, query: SearchQuery):
        await self.tracker.enter()
        try:
            await asyncio.sleep(0.01)
        finally:
            await self.tracker.leave()
        return [ProviderTrack(name=f"{self.name}-{query.text}", provider=self.name)]


@pytest.mark.asyncio
async def test_gateway_respects_concurrency_limit() -> None:
    tracker = _Tracker()
    providers = {
        "a": _RecordingProvider(name="a", tracker=tracker),
        "b": _RecordingProvider(name="b", tracker=tracker),
    }
    policy = ProviderRetryPolicy(
        timeout_ms=100, retry_max=0, backoff_base_ms=10, jitter_pct=0.0
    )
    config = ProviderGatewayConfig(
        max_concurrency=1,
        default_policy=policy,
        provider_policies={"a": policy, "b": policy},
    )
    gateway = ProviderGateway(providers=providers, config=config)

    await gateway.search_many(
        ["a", "b"], SearchQuery(text="hello", artist=None, limit=5)
    )

    assert tracker.max_active == 1
