"""Unit tests for :mod:`app.services.cache.ResponseCache`."""

from __future__ import annotations

import asyncio

import pytest

from app.services.cache import CacheEntry, ResponseCache


class StubClock:
    """Deterministic clock used to control cache expiry in tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._current = start

    def __call__(self) -> float:
        return self._current

    def advance(self, seconds: float) -> None:
        self._current += seconds


def make_entry(path_template: str = "/resource") -> CacheEntry:
    """Create a cache entry populated with default metadata."""

    return CacheEntry(
        key="",
        path_template=path_template,
        status_code=200,
        body=b"payload",
        headers={
            "Cache-Control": "max-age=60",
            "ETag": "etag",
            "Last-Modified": "Thu, 01 Jan 1970 00:00:00 GMT",
        },
        media_type="application/json",
        etag="etag",
        last_modified="Thu, 01 Jan 1970 00:00:00 GMT",
        last_modified_ts=0,
        cache_control="max-age=60",
        vary=(),
        created_at=0.0,
        expires_at=None,
        ttl=0.0,
        stale_while_revalidate=None,
        stale_expires_at=None,
    )


def make_cache(
    clock: StubClock, *, max_items: int = 3, default_ttl: float = 30.0, fail_open: bool = True
) -> ResponseCache:
    """Construct a :class:`ResponseCache` bound to the provided clock."""

    return ResponseCache(
        max_items=max_items,
        default_ttl=default_ttl,
        fail_open=fail_open,
        time_func=clock,
        log_evictions=False,
    )


@pytest.fixture()
def stub_clock() -> StubClock:
    return StubClock()


def test_cache_entry_expires_after_ttl(stub_clock: StubClock) -> None:
    cache = make_cache(stub_clock, max_items=2, default_ttl=5.0)
    key = "GET:/artists/alpha"
    entry = make_entry("/artists/{artist_key}")

    async def run() -> None:
        await cache.set(key, entry, ttl=5.0)

        assert entry.expires_at == pytest.approx(5.0)
        assert entry.is_expired(stub_clock()) is False

        cached = await cache.get(key)
        assert cached is entry

        stub_clock.advance(4.9)
        assert cached.is_expired(stub_clock()) is False

        cached = await cache.get(key)
        assert cached is entry

        stub_clock.advance(0.2)
        assert entry.is_expired(stub_clock()) is True
        assert await cache.get(key) is None
        assert key not in cache._cache

    asyncio.run(run())


def test_lru_eviction_removes_least_recent_entry(stub_clock: StubClock) -> None:
    cache = make_cache(stub_clock, max_items=2, default_ttl=10.0)

    async def run() -> None:
        first_key = "GET:/artists/one"
        second_key = "GET:/artists/two"
        third_key = "GET:/artists/three"

        await cache.set(first_key, make_entry("/artists/{artist_key}"))
        await cache.set(second_key, make_entry("/artists/{artist_key}"))

        assert await cache.get(first_key) is cache._cache[first_key]

        await cache.set(third_key, make_entry("/artists/{artist_key}"))

        assert second_key not in cache._cache
        assert await cache.get(second_key) is None
        assert await cache.get(first_key) is cache._cache[first_key]
        assert await cache.get(third_key) is cache._cache[third_key]

    asyncio.run(run())


def test_invalidate_removes_exact_key(stub_clock: StubClock) -> None:
    cache = make_cache(stub_clock)

    async def run() -> None:
        key = "GET:/albums/alpha"
        await cache.set(key, make_entry("/albums/{album_id}"))

        assert await cache.get(key) is not None

        await cache.invalidate(key)

        assert await cache.get(key) is None
        assert key not in cache._cache

    asyncio.run(run())


def test_invalidate_prefix_removes_all_matching_keys(stub_clock: StubClock) -> None:
    cache = make_cache(stub_clock)

    async def run() -> None:
        await cache.set("GET:/shows/1", make_entry("/shows/{show_id}"))
        await cache.set("GET:/shows/2", make_entry("/shows/{show_id}"))
        await cache.set("POST:/shows", make_entry("/shows"))

        removed = await cache.invalidate_prefix("GET:/shows/")

        assert removed == 2
        assert "GET:/shows/1" not in cache._cache
        assert "GET:/shows/2" not in cache._cache
        assert "POST:/shows" in cache._cache

    asyncio.run(run())


def test_invalidate_path_supports_template_matching(stub_clock: StubClock) -> None:
    cache = make_cache(stub_clock)

    async def run() -> None:
        await cache.set("GET:/playlists/123", make_entry("/playlists/{playlist_id}"))
        await cache.set("POST:/playlists/123", make_entry("/playlists/123"))

        removed = await cache.invalidate_path("/playlists/456", method="GET")

        assert removed == 1
        assert "GET:/playlists/123" not in cache._cache
        assert "POST:/playlists/123" in cache._cache

    asyncio.run(run())


def test_invalidate_pattern_uses_regex_matching(stub_clock: StubClock) -> None:
    cache = make_cache(stub_clock)

    async def run() -> None:
        await cache.set("GET:/artists/alpha", make_entry("/artists/{artist_key}"))
        await cache.set("GET:/artists/beta", make_entry("/artists/{artist_key}"))
        await cache.set("GET:/albums/alpha", make_entry("/albums/{album_id}"))

        removed = await cache.invalidate_pattern(r"artists/.+")

        assert removed == 2
        assert "GET:/artists/alpha" not in cache._cache
        assert "GET:/artists/beta" not in cache._cache
        assert "GET:/albums/alpha" in cache._cache

    asyncio.run(run())


def test_fail_open_suppresses_errors(stub_clock: StubClock) -> None:
    cache = make_cache(stub_clock, fail_open=True)

    async def run() -> None:
        class FailingLock:
            async def __aenter__(self) -> None:  # pragma: no cover - simple stub
                raise RuntimeError("boom")

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # pragma: no cover - simple stub
                return False

        cache._lock = FailingLock()  # type: ignore[assignment]

        assert await cache.get("missing") is None

        await cache.set("GET:/boom", make_entry("/boom"))

        assert "GET:/boom" not in cache._cache

    asyncio.run(run())
