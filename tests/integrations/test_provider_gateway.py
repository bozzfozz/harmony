from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from app.config import ExternalCallPolicy, ProviderProfile
from app.integrations.contracts import (
    ProviderDependencyError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderTrack,
    ProviderValidationError,
    SearchQuery,
)
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayConfig,
    ProviderGatewayDependencyError,
    ProviderGatewayNotFoundError,
    ProviderGatewayRateLimitedError,
    ProviderGatewayTimeoutError,
    ProviderGatewayValidationError,
    ProviderRetryPolicy,
)


@dataclass(slots=True)
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
        max_concurrency=5, default_policy=policy, provider_policies={"stub": policy}
    )


def _search_query() -> SearchQuery:
    return SearchQuery(text="song", artist=None, limit=10)


def test_gateway_config_from_settings_builds_policies() -> None:
    external = ExternalCallPolicy(
        timeout_ms=50,
        retry_max=-1,
        backoff_base_ms=0,
        jitter_pct=-0.5,
    )
    spotify_profile = ProviderProfile(
        name="Spotify",
        policy=ExternalCallPolicy(
            timeout_ms=150,
            retry_max=2,
            backoff_base_ms=5,
            jitter_pct=0.1,
        ),
    )

    config = ProviderGatewayConfig.from_settings(
        max_concurrency=0,
        external_policy=external,
        provider_profiles={"Spotify": spotify_profile},
    )

    assert config.max_concurrency == 1
    assert config.default_policy.timeout_ms == 100
    assert config.default_policy.retry_max == 0
    assert config.default_policy.backoff_base_ms == 1
    assert config.default_policy.jitter_pct == 0.0

    spotify_policy = config.policy_for("spotify")
    assert spotify_policy.timeout_ms == 150
    assert spotify_policy.retry_max == 2
    assert spotify_policy.backoff_base_ms == 5
    assert spotify_policy.jitter_pct == 0.1


@pytest.mark.asyncio
async def test_gateway_retries_and_applies_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
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

    results = await gateway.search_tracks("stub", _search_query())

    assert results[0].name == "song"
    assert sleeps == [0.025, 0.05]


@pytest.mark.asyncio
async def test_gateway_times_out_long_running_provider() -> None:
    async def slow_search(_query: SearchQuery):
        await asyncio.sleep(0.05)

    provider = _StubProvider(name="stub", responses=[slow_search])
    config = _make_config(retry_max=0)
    config = ProviderGatewayConfig(
        max_concurrency=1,
        default_policy=ProviderRetryPolicy(
            timeout_ms=10, retry_max=0, backoff_base_ms=10, jitter_pct=0.0
        ),
        provider_policies={
            "stub": ProviderRetryPolicy(
                timeout_ms=10, retry_max=0, backoff_base_ms=10, jitter_pct=0.0
            )
        },
    )
    gateway = ProviderGateway(providers={"stub": provider}, config=config)

    with pytest.raises(ProviderGatewayTimeoutError):
        await gateway.search_tracks("stub", _search_query())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_error, expected_error",
    [
        (
            ProviderValidationError("stub", "invalid", status_code=400),
            ProviderGatewayValidationError,
        ),
        (
            ProviderRateLimitedError(
                "stub",
                "limited",
                retry_after_ms=5,
                retry_after_header="1",
            ),
            ProviderGatewayRateLimitedError,
        ),
        (ProviderNotFoundError("stub", "missing", status_code=404), ProviderGatewayNotFoundError),
        (ProviderDependencyError("stub", "dep", status_code=502), ProviderGatewayDependencyError),
    ],
)
async def test_gateway_maps_provider_errors(
    provider_error: Exception, expected_error: type[Exception]
) -> None:
    provider = _StubProvider(name="stub", responses=[provider_error])
    config = _make_config(retry_max=0)
    gateway = ProviderGateway(providers={"stub": provider}, config=config)

    with pytest.raises(expected_error):
        await gateway.search_tracks("stub", _search_query())
