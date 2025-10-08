from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from app.integrations.contracts import (ProviderDependencyError, ProviderTrack,
                                        SearchQuery)
from app.integrations.provider_gateway import (ProviderGateway,
                                               ProviderGatewayConfig,
                                               ProviderGatewayTimeoutError,
                                               ProviderRetryPolicy)


@dataclass
class _StubProvider:
    name: str
    responses: list[Any]

    async def search_tracks(self, query: SearchQuery):
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            return await result(query)
        return result


def _make_config(
    *, retry_max: int = 2, backoff_ms: int = 10, jitter: float = 0.0
) -> ProviderGatewayConfig:
    policy = ProviderRetryPolicy(
        timeout_ms=100,
        retry_max=retry_max,
        backoff_base_ms=backoff_ms,
        jitter_pct=jitter,
    )
    return ProviderGatewayConfig(
        max_concurrency=5,
        default_policy=policy,
        provider_policies={"stub": policy},
    )


def _query() -> SearchQuery:
    return SearchQuery(text="track", artist=None, limit=10)


@pytest.mark.asyncio
async def test_gateway_retries_with_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _StubProvider(
        name="stub",
        responses=[
            ProviderDependencyError("stub", "dep"),
            ProviderDependencyError("stub", "dep"),
            [ProviderTrack(name="song", provider="stub")],
        ],
    )
    config = _make_config(retry_max=3, backoff_ms=25, jitter=0.0)
    gateway = ProviderGateway(providers={"stub": provider}, config=config)

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    results = await gateway.search_tracks("stub", _query())

    assert [track.name for track in results] == ["song"]
    assert sleeps == [0.025, 0.05]


@pytest.mark.asyncio
async def test_gateway_times_out_provider_call() -> None:
    async def slow_search(_query: SearchQuery):
        await asyncio.sleep(0.05)

    provider = _StubProvider(name="stub", responses=[slow_search])
    config = ProviderGatewayConfig(
        max_concurrency=1,
        default_policy=ProviderRetryPolicy(
            timeout_ms=10,
            retry_max=0,
            backoff_base_ms=10,
            jitter_pct=0.0,
        ),
        provider_policies={
            "stub": ProviderRetryPolicy(
                timeout_ms=10,
                retry_max=0,
                backoff_base_ms=10,
                jitter_pct=0.0,
            )
        },
    )
    gateway = ProviderGateway(providers={"stub": provider}, config=config)

    with pytest.raises(ProviderGatewayTimeoutError):
        await gateway.search_tracks("stub", _query())
