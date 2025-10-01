from __future__ import annotations

import pytest

from app.services.cache import CacheEntry, ResponseCache


@pytest.mark.asyncio()
async def test_cache_logs_use_contract(monkeypatch) -> None:
    clock = {"now": 1.0}

    def _time() -> float:
        return clock["now"]

    captured: list[tuple[str, dict]] = []

    def _capture(logger, event_name: str, /, **fields):
        captured.append((event_name, fields))

    monkeypatch.setattr("app.services.cache.log_event", _capture)

    cache = ResponseCache(max_items=10, default_ttl=1.0, fail_open=True, time_func=_time)

    entry = CacheEntry(
        key="",  # populated by cache
        path_template="/demo",
        status_code=200,
        body=b"{}",
        headers={},
        media_type="application/json",
        etag="etag",
        last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
        last_modified_ts=0,
        cache_control="max-age=60",
        vary=(),
        created_at=0.0,
        expires_at=None,
    )

    await cache.set("demo", entry)
    store_events = [payload for name, payload in captured if name == "cache.store"]
    assert store_events and store_events[-1]["status"] == "stored"

    hit = await cache.get("demo")
    assert hit is not None
    hit_events = [payload for name, payload in captured if name == "cache.hit"]
    assert hit_events and hit_events[-1]["status"] == "hit"

    miss = await cache.get("missing")
    assert miss is None
    miss_events = [payload for name, payload in captured if name == "cache.miss"]
    assert miss_events and miss_events[-1]["status"] == "miss"
