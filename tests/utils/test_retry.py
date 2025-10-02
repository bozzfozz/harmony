import asyncio
from typing import List

import pytest

from app.utils.retry import RetryDirective, exp_backoff_delays, with_retry


def test_exp_backoff_delays_with_jitter():
    assert exp_backoff_delays(100, 4, 20) == [120, 240, 480, 960]


def test_exp_backoff_delays_without_jitter():
    assert exp_backoff_delays(50, 3, 0) == [50, 100, 200]


@pytest.mark.asyncio
async def test_with_retry_success(monkeypatch):
    calls: List[int] = []
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def operation() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("transient")
        return "ok"

    def classify(exc: Exception) -> RetryDirective:
        assert isinstance(exc, TimeoutError)
        return RetryDirective(retry=True, error=exc)

    result = await with_retry(
        operation,
        attempts=3,
        base_ms=10,
        jitter_pct=0,
        timeout_ms=None,
        classify_err=classify,
    )

    assert result == "ok"
    assert len(calls) == 3
    assert sleep_calls == [0.01, 0.02]


@pytest.mark.asyncio
async def test_with_retry_propagates_error(monkeypatch):
    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def operation() -> str:
        raise ValueError("boom")

    def classify(exc: Exception) -> RetryDirective:
        return RetryDirective(retry=False, error=exc)

    with pytest.raises(ValueError):
        await with_retry(
            operation,
            attempts=2,
            base_ms=5,
            jitter_pct=0,
            timeout_ms=None,
            classify_err=classify,
        )
