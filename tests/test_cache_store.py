from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.cache import CacheEntry, ResponseCache


class TimeStub:
    def __init__(self) -> None:
        self._value = 0.0

    def advance(self, seconds: float) -> None:
        self._value += seconds

    def __call__(self) -> float:
        return self._value


def _make_entry(
    path: str, body: bytes, *, last_modified: datetime | None = None
) -> CacheEntry:
    last_mod = last_modified or datetime.now(timezone.utc)
    last_mod_ts = last_mod.timestamp()
    return CacheEntry(
        key="",
        path_template=path,
        status_code=200,
        body=body,
        headers={
            "ETag": '"abc"',
            "Last-Modified": last_mod.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "Cache-Control": "public, max-age=1",
        },
        media_type="application/json",
        etag='"abc"',
        last_modified=last_mod.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        last_modified_ts=last_mod_ts,
        cache_control="public, max-age=1",
        vary=("Authorization",),
        created_at=0.0,
        expires_at=None,
        ttl=1.0,
        stale_while_revalidate=None,
        stale_expires_at=None,
    )


@pytest.mark.asyncio
async def test_cache_entry_expires_after_ttl() -> None:
    clock = TimeStub()
    cache = ResponseCache(max_items=8, default_ttl=5, time_func=clock, fail_open=True)
    entry = _make_entry("/api/v1/system/status", b"{}")
    await cache.set("GET:/api/v1/system/status:0:0:anon", entry, ttl=3)

    clock.advance(2)
    cached = await cache.get("GET:/api/v1/system/status:0:0:anon")
    assert cached is not None

    clock.advance(2)
    expired = await cache.get("GET:/api/v1/system/status:0:0:anon")
    assert expired is None


@pytest.mark.asyncio
async def test_lru_eviction_discards_oldest_entries() -> None:
    clock = TimeStub()
    cache = ResponseCache(max_items=2, default_ttl=30, time_func=clock, fail_open=True)
    first = _make_entry("/one", b"first")
    second = _make_entry("/two", b"second")
    third = _make_entry("/three", b"third")

    await cache.set("GET:/one:0:0:anon", first)
    await cache.set("GET:/two:0:0:anon", second)

    # Access the first entry to mark it as most recently used
    assert await cache.get("GET:/one:0:0:anon") is not None

    await cache.set("GET:/three:0:0:anon", third)

    assert await cache.get("GET:/one:0:0:anon") is not None
    assert await cache.get("GET:/two:0:0:anon") is None
    assert await cache.get("GET:/three:0:0:anon") is not None


@pytest.mark.asyncio
async def test_invalidate_prefix_removes_related_entries() -> None:
    clock = TimeStub()
    cache = ResponseCache(max_items=4, default_ttl=30, time_func=clock, fail_open=True)
    first = _make_entry("/alpha", b"first")
    second = _make_entry("/alpha", b"second")

    await cache.set("GET:/alpha:0:0:anon", first)
    await cache.set("GET:/alpha:0:1:anon", second)

    removed = await cache.invalidate_prefix("GET:/alpha")
    assert removed == 2
    assert await cache.get("GET:/alpha:0:0:anon") is None
    assert await cache.get("GET:/alpha:0:1:anon") is None
