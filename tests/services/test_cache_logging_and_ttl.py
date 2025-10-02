from __future__ import annotations

import pytest

from app.services.cache import CacheEntry, ResponseCache


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def advance(self, seconds: float) -> None:
        self.value += seconds

    def __call__(self) -> float:
        return self.value


def _entry() -> CacheEntry:
    return CacheEntry(
        key="",
        path_template="/search",
        status_code=200,
        body=b"{}",
        headers={},
        media_type="application/json",
        etag="etag",
        last_modified="",
        last_modified_ts=0,
        cache_control="public",
        vary=tuple(),
        created_at=0.0,
        expires_at=None,
    )


@pytest.mark.asyncio
async def test_cache_logging_and_ttl(monkeypatch) -> None:
    clock = _Clock()
    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(logger, event: str, /, **fields: object) -> None:
        captured.append((event, fields))

    monkeypatch.setattr("app.services.cache.log_event", _capture)

    cache = ResponseCache(max_items=2, default_ttl=5, time_func=clock)

    assert await cache.get("key") is None
    last = _last_service_event(captured)
    assert last["operation"] == "miss"
    assert last["status"] == "miss"

    entry = _entry()
    await cache.set("key", entry)
    assert entry.expires_at == clock.value + 5
    last = _last_service_event(captured)
    assert last["operation"] == "store"
    assert last["status"] == "stored"

    cached = await cache.get("key")
    assert cached is entry
    last = _last_service_event(captured)
    assert last["operation"] == "hit"
    assert last["status"] == "hit"

    clock.advance(6)
    assert await cache.get("key") is None
    last = _last_service_event(captured)
    assert last["operation"] == "expired"
    assert last["status"] == "expired"


def _last_service_event(events: list[tuple[str, dict[str, object]]]) -> dict[str, object]:
    for name, payload in reversed(events):
        if name == "service.cache":
            return payload
    raise AssertionError("No service.cache event captured")
