from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Iterable

import aiohttp
import pytest

from app.config import SoulseekConfig
from app.core.soulseek_client import SoulseekClient


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self._headers = headers or {}

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:  # pragma: no cover - noop
        return None


class _FakeSession:
    def __init__(self, outcomes: Iterable[Any]) -> None:
        self._outcomes = deque(outcomes)
        self.closed = False

    def request(self, *_args: Any, **_kwargs: Any) -> Any:
        if not self._outcomes:
            raise RuntimeError("No more responses configured")
        result = self._outcomes.popleft()
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self) -> None:  # pragma: no cover - defensive
        self.closed = True


def _make_config(**overrides: Any) -> SoulseekConfig:
    base = SoulseekConfig(
        base_url="http://slskd",
        api_key=None,
        timeout_ms=1_000,
        retry_max=2,
        retry_backoff_base_ms=100,
        retry_jitter_pct=0.0,
        preferred_formats=("FLAC",),
        max_results=10,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@pytest.mark.asyncio
async def test_soulseek_client_retries_with_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        [
            aiohttp.ClientConnectionError("boom"),
            aiohttp.ClientConnectionError("boom again"),
            _FakeResponse(
                status=200,
                body="{}",
                headers={"Content-Type": "application/json"},
            ),
        ]
    )
    client = SoulseekClient(_make_config(), session=session)

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = await client._request("GET", "transfers/downloads")

    assert result == {}
    assert sleeps == [0.1, 0.2]


@pytest.mark.asyncio
async def test_soulseek_client_applies_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(
        [
            aiohttp.ClientConnectionError("boom"),
            aiohttp.ClientConnectionError("boom again"),
            _FakeResponse(
                status=200,
                body="{}",
                headers={"Content-Type": "application/json"},
            ),
        ]
    )
    client = SoulseekClient(
        _make_config(retry_jitter_pct=0.2),
        session=session,
    )

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    bounds: list[tuple[float, float]] = []

    def fake_uniform(lower: float, upper: float) -> float:
        bounds.append((lower, upper))
        return upper

    monkeypatch.setattr("app.utils.retry.random.uniform", fake_uniform)

    result = await client._request("GET", "transfers/downloads")

    assert result == {}
    assert sleeps == [0.12, 0.24]
    assert bounds == [(80.0, 120.0), (160.0, 240.0)]
