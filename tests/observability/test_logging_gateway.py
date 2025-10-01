from __future__ import annotations

import pytest

from app.config import ExternalCallPolicy
from app.integrations.contracts import ProviderTimeoutError, SearchQuery, TrackProvider
from app.integrations.provider_gateway import (
    ProviderGateway,
    ProviderGatewayConfig,
    ProviderRetryPolicy,
)


class _StubProvider:
    def __init__(
        self, name: str, *, result: list | None = None, error: Exception | None = None
    ) -> None:
        self.name = name
        self._result = result or []
        self._error = error

    async def search_tracks(self, query: SearchQuery) -> list:
        if self._error is not None:
            raise self._error
        return list(self._result)


@pytest.fixture()
def gateway_policy() -> ProviderRetryPolicy:
    base = ExternalCallPolicy(timeout_ms=100, retry_max=0, backoff_base_ms=1, jitter_pct=0.0)
    return ProviderRetryPolicy.from_external(base)


def _build_gateway(provider: TrackProvider, policy: ProviderRetryPolicy) -> ProviderGateway:
    config = ProviderGatewayConfig(
        max_concurrency=2,
        default_policy=policy,
        provider_policies={provider.name.lower(): policy},
    )
    return ProviderGateway(providers={provider.name: provider}, config=config)


@pytest.mark.asyncio()
async def test_logging_dependency_wraps_provider_calls_and_sets_status(
    monkeypatch, gateway_policy
) -> None:
    provider = _StubProvider("Dummy", result=[])
    gateway = _build_gateway(provider, gateway_policy)

    captured: list[tuple[str, dict]] = []

    def _capture(logger, event_name: str, /, **fields):
        captured.append((event_name, fields))

    monkeypatch.setattr("app.integrations.provider_gateway.log_event", _capture)
    result = await gateway.search_tracks("Dummy", SearchQuery(text="demo", artist=None, limit=1))
    assert result == []

    assert captured, "expected api.dependency event"
    event_name, payload = captured[-1]

    assert event_name == "api.dependency"
    assert payload["component"] == "provider_gateway"
    assert payload["dependency"] == "Dummy"
    assert payload["status"] == "ok"
    assert payload["operation"] == "search_tracks"
    assert payload["attempt"] == 1
    assert payload["max_attempts"] == 1
    assert isinstance(payload["duration_ms"], int)


@pytest.mark.asyncio()
async def test_logging_dependency_records_errors(monkeypatch, gateway_policy) -> None:
    provider = _StubProvider("Dummy", error=ProviderTimeoutError("Dummy", timeout_ms=42))
    gateway = _build_gateway(provider, gateway_policy)

    captured: list[tuple[str, dict]] = []

    def _capture(logger, event_name: str, /, **fields):
        captured.append((event_name, fields))

    monkeypatch.setattr("app.integrations.provider_gateway.log_event", _capture)
    response = await gateway.search_many(["Dummy"], SearchQuery(text="demo", artist=None, limit=1))
    assert response.status == "failed"

    assert captured, "expected api.dependency event"
    event_name, payload = captured[-1]

    assert event_name == "api.dependency"
    assert payload["status"] == "error"
    assert payload["dependency"] == "Dummy"
    assert payload["error"] == "ProviderGatewayTimeoutError"
    assert payload["timeout_ms"] == 42
    assert payload["attempt"] == 1
