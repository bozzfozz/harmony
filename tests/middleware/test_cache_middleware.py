"""Cache middleware behavior tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from email.utils import parsedate_to_datetime
import hashlib
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.config import CacheMiddlewareConfig, CacheRule
from app.middleware.cache import CacheMiddleware
from app.services.cache import (
    CacheEntry,
    build_query_hash,
    playlist_detail_cache_key,
    playlist_filters_hash,
    playlist_list_cache_key,
    resolve_auth_variant,
)


class FakeResponseCache:
    """Minimal async cache implementation for middleware tests."""

    def __init__(
        self,
        *,
        now: Callable[[], float] | None = None,
        raise_on_set: bool = False,
    ) -> None:
        self._now = now or time.time
        self.raise_on_set = raise_on_set
        self.storage: dict[str, CacheEntry] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, CacheEntry, float | None]] = []

    async def get(self, key: str) -> CacheEntry | None:  # type: ignore[override]
        self.get_calls.append(key)
        entry = self.storage.get(key)
        return entry

    async def set(self, key: str, entry: CacheEntry, ttl: float | None = None) -> None:  # type: ignore[override]
        self.set_calls.append((key, entry, ttl))
        if self.raise_on_set:
            raise RuntimeError("cache unavailable")
        now = self._now()
        ttl_value = entry.ttl if ttl is None else float(ttl)
        entry.key = key
        entry.created_at = now
        entry.ttl = ttl_value
        entry.expires_at = now + ttl_value if ttl_value is not None else None
        if entry.stale_while_revalidate is not None:
            entry.stale_expires_at = now + ttl_value + max(0.0, entry.stale_while_revalidate)
        else:
            entry.stale_expires_at = None
        self.storage[key] = entry

    @property
    def last_get_key(self) -> str | None:
        return self.get_calls[-1] if self.get_calls else None

    @property
    def last_set(self):
        return self.set_calls[-1] if self.set_calls else None


@pytest.fixture(name="base_config")
def base_config_fixture() -> CacheMiddlewareConfig:
    return CacheMiddlewareConfig(
        enabled=True,
        default_ttl=60,
        max_items=128,
        etag_strategy="strong",
        fail_open=True,
        stale_while_revalidate=None,
        cacheable_paths=(),
        write_through=True,
        log_evictions=False,
    )


def test_html_responses_enforce_no_store(base_config: CacheMiddlewareConfig) -> None:
    cache = FakeResponseCache()
    app = FastAPI()

    @app.get("/page")
    def html_page() -> Response:
        return Response("<h1>hello</h1>", media_type="text/html")

    app.add_middleware(CacheMiddleware, cache=cache, config=base_config)

    with TestClient(app) as client:
        response = client.get("/page")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "Vary" in response.headers


def test_cached_response_generates_etag_and_last_modified(
    base_config: CacheMiddlewareConfig,
) -> None:
    cache = FakeResponseCache()
    config = replace(
        base_config,
        cacheable_paths=(CacheRule(pattern=r"^/json$", ttl=30, stale_while_revalidate=120),),
    )
    app = FastAPI()

    @app.get("/json")
    def json_endpoint() -> JSONResponse:
        return JSONResponse({"message": "hi"})

    app.add_middleware(CacheMiddleware, cache=cache, config=config)

    with TestClient(app) as client:
        response = client.get("/json")

    assert response.status_code == 200
    assert "ETag" in response.headers
    assert "Last-Modified" in response.headers
    assert response.headers["Cache-Control"] == "public, max-age=30, stale-while-revalidate=120"
    last_modified = parsedate_to_datetime(response.headers["Last-Modified"])
    assert last_modified is not None

    assert cache.last_set is not None
    key, entry, ttl = cache.last_set
    assert key is not None
    assert ttl == pytest.approx(30.0)
    assert entry.etag == response.headers["ETag"]
    assert entry.last_modified == response.headers["Last-Modified"]
    expected_digest = hashlib.blake2b(response.content, digest_size=16).hexdigest()
    assert entry.etag == f'"{expected_digest}"'


def test_playlist_list_cache_key_used_for_collection_requests(
    base_config: CacheMiddlewareConfig,
) -> None:
    cache = FakeResponseCache()
    config = replace(
        base_config,
        cacheable_paths=(
            CacheRule(pattern=r"^/spotify/playlists$", ttl=45, stale_while_revalidate=None),
        ),
    )
    app = FastAPI()

    @app.get("/spotify/playlists")
    def list_playlists(limit: int = 20, source: str | None = None) -> JSONResponse:
        return JSONResponse({"items": [], "limit": limit, "source": source})

    app.add_middleware(CacheMiddleware, cache=cache, config=config)

    params = [("source", "liked"), ("limit", "5")]
    with TestClient(app) as client:
        response = client.get("/spotify/playlists", params=params)

    assert response.status_code == 200
    expected_hash = playlist_filters_hash("source=liked&limit=5")
    expected_key = playlist_list_cache_key(filters_hash=expected_hash)
    assert cache.last_get_key == expected_key
    assert cache.last_set is not None
    key, _entry, _ttl = cache.last_set
    assert key == expected_key


def test_playlist_detail_cache_key_includes_auth_and_query(
    base_config: CacheMiddlewareConfig,
) -> None:
    cache = FakeResponseCache()
    config = replace(
        base_config,
        cacheable_paths=(
            CacheRule(pattern=r"^/spotify/playlists$", ttl=45, stale_while_revalidate=None),
            CacheRule(pattern=r"^/spotify/playlists/[^/]+$", ttl=45, stale_while_revalidate=None),
        ),
    )
    app = FastAPI()

    @app.get("/spotify/playlists/{playlist_id}")
    def get_playlist(playlist_id: str, include: str | None = None) -> JSONResponse:
        return JSONResponse({"id": playlist_id, "include": include})

    app.add_middleware(CacheMiddleware, cache=cache, config=config)

    headers = {"Authorization": "Bearer token-xyz"}
    params = {"include": "tracks"}
    playlist_id = "abc123"
    with TestClient(app) as client:
        response = client.get(f"/spotify/playlists/{playlist_id}", headers=headers, params=params)

    assert response.status_code == 200
    query_hash = build_query_hash("include=tracks")
    auth_variant = resolve_auth_variant(headers["Authorization"])
    prefix = playlist_detail_cache_key(playlist_id)
    expected_key = f"{prefix}:GET:{query_hash}:{auth_variant}"
    middleware = CacheMiddleware(app, cache=cache, config=config)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": f"/spotify/playlists/{playlist_id}",
        "raw_path": f"/spotify/playlists/{playlist_id}".encode("utf-8"),
        "root_path": "",
        "app": app,
        "headers": [(b"authorization", headers["Authorization"].encode("latin-1"))],
        "query_string": b"include=tracks",
        "path_params": {"playlist_id": playlist_id},
    }

    async def _receive() -> dict[str, object]:
        return {"type": "http.request"}

    request = Request(scope, _receive)
    cache_key = middleware._build_playlist_cache_key(
        request,
        path_template="/spotify/playlists/{playlist_id}",
        raw_path=f"/spotify/playlists/{playlist_id}",
        trimmed_path=f"/spotify/playlists/{playlist_id}",
    )
    assert cache_key == expected_key


def test_fail_open_returns_original_response_when_store_fails(
    base_config: CacheMiddlewareConfig,
) -> None:
    cache = FakeResponseCache(raise_on_set=True)
    config = replace(
        base_config,
        cacheable_paths=(CacheRule(pattern=r"^/json$", ttl=25, stale_while_revalidate=None),),
    )
    app = FastAPI()

    @app.get("/json")
    def json_endpoint() -> JSONResponse:
        return JSONResponse({"message": "fail-open"})

    app.add_middleware(CacheMiddleware, cache=cache, config=config)
    with TestClient(app) as client:
        response = client.get("/json")

    assert response.status_code == 200
    assert response.json() == {"message": "fail-open"}
    assert cache.last_set is not None
    key, _entry, _ttl = cache.last_set
    assert key is not None
    assert key not in cache.storage
    assert response.headers["Cache-Control"] == "public, max-age=25"
    assert "ETag" not in response.headers
