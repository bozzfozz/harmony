import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import spotify_router


def test_get_playlists_propagates_http_exception(monkeypatch):
    def raise_http_exception():
        raise HTTPException(status_code=404, detail="missing")

    monkeypatch.setattr(
        spotify_router,
        "client",
        SimpleNamespace(get_user_playlists_metadata_only=raise_http_exception),
    )

    async def runner():
        with pytest.raises(HTTPException) as exc_info:
            await spotify_router.get_playlists()

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "missing"

    asyncio.run(runner())


def test_get_playlists_wraps_generic_exception(monkeypatch):
    def raise_runtime_error():
        raise RuntimeError("boom")

    monkeypatch.setattr(
        spotify_router,
        "client",
        SimpleNamespace(get_user_playlists_metadata_only=raise_runtime_error),
    )

    async def runner():
        with pytest.raises(HTTPException) as exc_info:
            await spotify_router.get_playlists()

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "boom"

    asyncio.run(runner())


def test_search_tracks_propagates_http_exception(monkeypatch):
    def raise_http_exception(_query: str):
        raise HTTPException(status_code=429, detail="rate limited")

    monkeypatch.setattr(
        spotify_router,
        "client",
        SimpleNamespace(search_tracks=raise_http_exception),
    )

    async def runner():
        with pytest.raises(HTTPException) as exc_info:
            await spotify_router.search_tracks(query="test")

        assert exc_info.value.status_code == 429
        assert exc_info.value.detail == "rate limited"

    asyncio.run(runner())


def test_search_tracks_wraps_generic_exception(monkeypatch):
    def raise_runtime_error(_query: str):
        raise RuntimeError("oops")

    monkeypatch.setattr(
        spotify_router,
        "client",
        SimpleNamespace(search_tracks=raise_runtime_error),
    )

    async def runner():
        with pytest.raises(HTTPException) as exc_info:
            await spotify_router.search_tracks(query="query")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "oops"

    asyncio.run(runner())
