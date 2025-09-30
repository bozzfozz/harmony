from __future__ import annotations

from typing import Any, Iterator

import pytest

from app import dependencies as deps
from app.main import app


def _reset_config_cache() -> None:
    deps.get_app_config.cache_clear()


@pytest.fixture(autouse=True)
def _clear_config_cache() -> Iterator[None]:
    _reset_config_cache()
    try:
        yield
    finally:
        _reset_config_cache()


@pytest.fixture
def worker_config_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def fake_log_event(logger: Any, event: str, /, **fields: Any) -> None:
        captured.append({"logger": logger, "event": event, **fields})

    monkeypatch.setattr("app.main.log_event", fake_log_event)
    return captured


@pytest.mark.asyncio
async def test_config_event_emitted_on_startup(
    monkeypatch: pytest.MonkeyPatch, worker_config_events: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")

    async with app.router.lifespan_context(app):
        pass

    assert len(worker_config_events) == 1

    event = worker_config_events[0]
    assert event["event"] == "worker.config"
    assert event["component"] == "bootstrap"
    assert event["status"] == "ok"
    assert isinstance(event["meta"], dict)


@pytest.mark.asyncio
async def test_config_event_contains_expected_keys(
    monkeypatch: pytest.MonkeyPatch, worker_config_events: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")
    monkeypatch.setenv("WATCHLIST_INTERVAL", "123.5")
    monkeypatch.setenv("WATCHLIST_MAX_CONCURRENCY", "7")
    monkeypatch.setenv("WATCHLIST_RETRY_BUDGET_PER_ARTIST", "9")
    monkeypatch.setenv("WATCHLIST_BACKOFF_BASE_MS", "500")
    monkeypatch.setenv("WATCHLIST_JITTER_PCT", "0.35")
    monkeypatch.setenv("WORKER_VISIBILITY_TIMEOUT_S", "45")
    monkeypatch.setenv("PROVIDER_MAX_CONCURRENCY", "6")
    monkeypatch.setenv("SLSKD_TIMEOUT_MS", "15000")
    monkeypatch.setenv("SLSKD_RETRY_MAX", "5")
    monkeypatch.setenv("SLSKD_RETRY_BACKOFF_BASE_MS", "400")
    monkeypatch.setenv("SLSKD_JITTER_PCT", "18.5")
    monkeypatch.setenv("FEATURE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("FEATURE_RATE_LIMITING", "1")

    async with app.router.lifespan_context(app):
        pass

    assert len(worker_config_events) == 1
    meta = worker_config_events[0]["meta"]

    watchlist = meta["watchlist"]
    assert watchlist["interval_s"] == pytest.approx(123.5)
    assert watchlist["concurrency"] == 7
    assert watchlist["retry_budget_per_artist"] == 9
    assert watchlist["backoff_base_ms"] == 500
    assert watchlist["jitter_pct"] == pytest.approx(0.35)

    queue = meta["queue"]
    assert queue["visibility_timeout_s"] == 45

    providers = meta["providers"]
    assert providers["max_concurrency"] == 6

    slskd = providers["slskd"]
    assert slskd["timeout_ms"] == 15000
    assert slskd["retry_max"] == 5
    assert slskd["retry_backoff_base_ms"] == 400
    assert slskd["jitter_pct"] == pytest.approx(18.5)

    features = meta["features"]
    assert features["require_auth"] is True
    assert features["rate_limiting"] is True
    assert features["workers_disabled"] is True
