import asyncio

import pytest

from app.utils.time import monotonic_ms, now_utc, sleep_jitter_ms


def test_now_utc_is_timezone_aware():
    current = now_utc()
    assert current.tzinfo is not None
    assert current.utcoffset() is not None


def test_monotonic_ms_increases():
    first = monotonic_ms()
    second = monotonic_ms()
    assert second >= first


@pytest.mark.asyncio
async def test_sleep_jitter_ms(monkeypatch):
    recorded: list[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = await sleep_jitter_ms(100, 50)
    assert recorded
    slept = recorded[0]
    assert 0.05 <= slept <= 0.15
    assert pytest.approx(result, rel=0.0) == slept
