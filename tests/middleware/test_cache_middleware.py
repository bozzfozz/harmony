from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from app.config import load_config
from app.middleware.cache import CacheMiddleware
from app.services.cache import ResponseCache


def _create_app(
    env: dict[str, str],
    routes: dict[str, Callable[[], dict[str, object]]],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, dict[str, int], ResponseCache]:
    relevant_keys = {
        "CACHE_DEFAULT_TTL_S",
        "CACHE_STALE_WHILE_REVALIDATE_S",
        "CACHE_FAIL_OPEN",
        "CACHE_ENABLED",
        "CACHE_MAX_ITEMS",
        "CACHE_STRATEGY_ETAG",
        "CACHEABLE_PATHS",
        "DATABASE_URL",
    }
    for key in relevant_keys:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    config = load_config()
    cache_config = config.middleware.cache
    app = FastAPI()
    app.state.api_base_path = config.api_base_path

    call_counts: dict[str, int] = {path: 0 for path in routes}

    for path, handler in routes.items():

        async def _endpoint(
            handler: Callable[[], dict[str, object]] = handler,
            path: str = path,
        ) -> dict[str, object]:
            call_counts[path] += 1
            return handler()

        app.get(path)(_endpoint)  # type: ignore[misc]

    response_cache = ResponseCache(
        max_items=cache_config.max_items,
        default_ttl=float(cache_config.default_ttl),
        fail_open=cache_config.fail_open,
    )
    app.state.response_cache = response_cache
    app.add_middleware(CacheMiddleware, cache=response_cache, config=cache_config)

    return TestClient(app), call_counts, response_cache


def test_cache_control_uses_path_specific_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "DATABASE_URL": "postgres://test:test@localhost:5432/harmony",
        "CACHE_DEFAULT_TTL_S": "45",
        "CACHE_STALE_WHILE_REVALIDATE_S": "90",
        "CACHEABLE_PATHS": "^/cache/me$|120|30, ^/cache/default$||",
    }

    routes = {
        "/cache/me": lambda: {"path": "me"},
        "/cache/default": lambda: {"path": "default"},
    }

    client, calls, _ = _create_app(env, routes, monkeypatch)

    me_response = client.get("/cache/me")
    assert me_response.status_code == 200
    assert me_response.headers["Cache-Control"] == "public, max-age=120, stale-while-revalidate=30"
    assert calls["/cache/me"] == 1

    cached_me = client.get("/cache/me")
    assert cached_me.status_code == 200
    assert cached_me.headers["Cache-Control"] == "public, max-age=120, stale-while-revalidate=30"
    assert calls["/cache/me"] == 1

    default_response = client.get("/cache/default")
    assert default_response.status_code == 200
    assert (
        default_response.headers["Cache-Control"] == "public, max-age=45, stale-while-revalidate=90"
    )
    assert calls["/cache/default"] == 1

    cached_default = client.get("/cache/default")
    assert cached_default.status_code == 200
    assert (
        cached_default.headers["Cache-Control"] == "public, max-age=45, stale-while-revalidate=90"
    )
    assert calls["/cache/default"] == 1


def test_cache_fail_closed_propagates_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        "DATABASE_URL": "postgres://test:test@localhost:5432/harmony",
        "CACHE_FAIL_OPEN": "false",
        "CACHEABLE_PATHS": "^/boom$|10|",
    }

    client, _, cache = _create_app(env, {"/boom": lambda: {"ok": True}}, monkeypatch)

    class ExplodingDict(dict):
        def get(self, key):  # type: ignore[override]
            raise RuntimeError("boom")

    cache._cache = ExplodingDict()  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError):
        client.get("/boom")


def test_cache_fail_open_streaming_body_preserved_on_store_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {
        "DATABASE_URL": "postgres://test:test@localhost:5432/harmony",
        "CACHE_FAIL_OPEN": "true",
        "CACHEABLE_PATHS": "^/stream$|10|",
    }

    def streaming_route() -> StreamingResponse:
        async def iterator():
            yield b"streamed"

        return StreamingResponse(iterator(), media_type="text/plain")

    client, _, cache = _create_app(env, {"/stream": streaming_route}, monkeypatch)

    async def explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("store failed")

    monkeypatch.setattr(cache, "set", explode, raising=False)

    response = client.get("/stream")

    assert response.status_code == 200
    assert response.text == "streamed"


def test_playlist_tracks_cache_key_preserves_query_and_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relevant_keys = {
        "CACHE_DEFAULT_TTL_S",
        "CACHE_STALE_WHILE_REVALIDATE_S",
        "CACHE_FAIL_OPEN",
        "CACHE_ENABLED",
        "CACHE_MAX_ITEMS",
        "CACHE_STRATEGY_ETAG",
        "CACHEABLE_PATHS",
        "CACHE_WRITE_THROUGH",
        "CACHE_LOG_EVICTIONS",
        "DATABASE_URL",
    }
    for key in relevant_keys:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("DATABASE_URL", "postgres://test:test@localhost:5432/harmony")
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("CACHE_DEFAULT_TTL_S", "120")
    monkeypatch.setenv("CACHE_MAX_ITEMS", "50")
    monkeypatch.setenv("CACHEABLE_PATHS", "^/spotify/playlists/[^/]+/tracks$|60|")

    config = load_config()
    cache_config = config.middleware.cache

    app = FastAPI()
    app.state.api_base_path = config.api_base_path

    call_counts: dict[tuple[int, str], int] = {}

    @app.get("/spotify/playlists/{playlist_id}/tracks")
    async def playlist_tracks(
        request: Request, playlist_id: str, limit: int = 20
    ) -> dict[str, object]:
        header = request.headers.get("authorization") or "anon"
        key = (limit, header)
        call_counts[key] = call_counts.get(key, 0) + 1
        return {"playlist_id": playlist_id, "limit": limit, "authorization": header}

    response_cache = ResponseCache(
        max_items=cache_config.max_items,
        default_ttl=float(cache_config.default_ttl),
        fail_open=cache_config.fail_open,
        write_through=cache_config.write_through,
        log_evictions=cache_config.log_evictions,
    )

    app.state.response_cache = response_cache
    app.add_middleware(CacheMiddleware, cache=response_cache, config=cache_config)

    client = TestClient(app)

    auth_a = {"Authorization": "Bearer token-a"}
    auth_b = {"Authorization": "Bearer token-b"}

    first = client.get(
        "/spotify/playlists/playlist-1/tracks",
        params={"limit": 25},
        headers=auth_a,
    )
    assert first.status_code == 200
    assert first.json()["limit"] == 25
    assert call_counts[(25, "Bearer token-a")] == 1

    cached_same = client.get(
        "/spotify/playlists/playlist-1/tracks",
        params={"limit": 25},
        headers=auth_a,
    )
    assert cached_same.status_code == 200
    assert cached_same.json()["limit"] == 25
    assert call_counts[(25, "Bearer token-a")] == 1

    different_limit = client.get(
        "/spotify/playlists/playlist-1/tracks",
        params={"limit": 100},
        headers=auth_a,
    )
    assert different_limit.status_code == 200
    assert different_limit.json()["limit"] == 100
    assert call_counts[(100, "Bearer token-a")] == 1

    different_auth = client.get(
        "/spotify/playlists/playlist-1/tracks",
        params={"limit": 25},
        headers=auth_b,
    )
    assert different_auth.status_code == 200
    assert different_auth.json()["authorization"] == "Bearer token-b"
    assert call_counts[(25, "Bearer token-b")] == 1

    cached_auth_variant = client.get(
        "/spotify/playlists/playlist-1/tracks",
        params={"limit": 25},
        headers=auth_b,
    )
    assert cached_auth_variant.status_code == 200
    assert cached_auth_variant.json()["authorization"] == "Bearer token-b"
    assert call_counts[(25, "Bearer token-b")] == 1
