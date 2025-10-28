import pytest

from app.utils import time as time_utils


@pytest.mark.asyncio
async def test_sleep_jitter_ms_returns_milliseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, float] = {}

    async def fake_sleep(seconds: float) -> None:
        captured["seconds"] = seconds

    def fake_uniform(lower: float, upper: float) -> float:
        captured["lower"] = lower
        captured["upper"] = upper
        return (lower + upper) / 2.0

    monkeypatch.setattr(time_utils.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(time_utils.random, "uniform", fake_uniform)

    result_ms = await time_utils.sleep_jitter_ms(200, 25)

    assert captured["lower"] == pytest.approx(150.0)
    assert captured["upper"] == pytest.approx(250.0)
    assert result_ms == pytest.approx(200.0)
    assert captured["seconds"] == pytest.approx(result_ms / 1000.0)


@pytest.mark.asyncio
async def test_sleep_jitter_ms_clamps_negative_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        called.append(seconds)

    monkeypatch.setattr(time_utils.asyncio, "sleep", fake_sleep)

    result_ms = await time_utils.sleep_jitter_ms(-50, -10)

    assert result_ms == 0.0
    assert called == [0]
