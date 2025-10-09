import asyncio
from datetime import datetime, timezone

import pytest

from app.models import Playlist
from app.services.cache import (
    CacheEntry,
    ResponseCache,
    playlist_detail_cache_key,
    playlist_list_cache_key,
)
from app.utils.http_cache import compute_playlist_collection_metadata
from app.workers.playlist_sync_worker import PlaylistCacheInvalidator
from tests.simple_client import SimpleTestClient


def _build_entry(
    *,
    path_template: str,
    etag: str,
    last_modified: datetime,
) -> CacheEntry:
    headers = {
        "Content-Type": "application/json",
        "ETag": etag,
        "Last-Modified": last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        "Cache-Control": "public, max-age=60",
    }
    return CacheEntry(
        key="",
        path_template=path_template,
        status_code=200,
        body=b"{}",
        headers=headers,
        media_type="application/json",
        etag=etag,
        last_modified=headers["Last-Modified"],
        last_modified_ts=int(last_modified.replace(tzinfo=timezone.utc).timestamp()),
        cache_control=headers["Cache-Control"],
        vary=(),
        created_at=0.0,
        expires_at=None,
        ttl=60.0,
        stale_while_revalidate=None,
        stale_expires_at=None,
    )


def test_etag_last_modified_reflect_max_updated_at() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    newer = base.replace(day=2)
    playlist_a = Playlist(id="playlist-1", name="Focus", track_count=10)
    playlist_a.updated_at = newer
    playlist_b = Playlist(id="playlist-2", name="Calm", track_count=5)
    playlist_b.updated_at = base

    initial = compute_playlist_collection_metadata(
        [playlist_a, playlist_b], filters_hash="filters:v1"
    )
    assert initial.last_modified == newer

    playlist_a.updated_at = newer.replace(day=3)
    refreshed = compute_playlist_collection_metadata(
        [playlist_a, playlist_b], filters_hash="filters:v1"
    )

    assert initial.etag != refreshed.etag
    assert refreshed.last_modified == playlist_a.updated_at

    filters_changed = compute_playlist_collection_metadata(
        [playlist_a, playlist_b], filters_hash="filters:v2"
    )
    assert filters_changed.etag != refreshed.etag


@pytest.mark.asyncio
async def test_playlist_list_busts_cache_on_update() -> None:
    cache = ResponseCache(max_items=20, default_ttl=60.0)
    loop = asyncio.get_running_loop()
    invalidator = PlaylistCacheInvalidator(cache, loop=loop)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    list_key = playlist_list_cache_key(filters_hash="0")
    await cache.set(
        list_key,
        _build_entry(
            path_template="/spotify/playlists", etag='"list"', last_modified=now
        ),
    )

    detail_key = playlist_detail_cache_key("playlist-1")
    await cache.set(
        detail_key,
        _build_entry(
            path_template="/spotify/playlists/{playlist_id}/tracks",
            etag='"detail"',
            last_modified=now,
        ),
    )

    assert await cache.get(list_key) is not None
    assert await cache.get(detail_key) is not None

    await asyncio.to_thread(invalidator.invalidate, ["playlist-1"])

    assert await cache.get(list_key) is None
    assert await cache.get(detail_key) is None


@pytest.mark.asyncio
async def test_playlist_detail_busts_cache_on_update() -> None:
    cache = ResponseCache(max_items=20, default_ttl=60.0)
    loop = asyncio.get_running_loop()
    invalidator = PlaylistCacheInvalidator(cache, loop=loop)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    target_key = playlist_detail_cache_key("playlist-1")
    other_key = playlist_detail_cache_key("playlist-2")

    await cache.set(
        target_key,
        _build_entry(
            path_template="/spotify/playlists/{playlist_id}/tracks",
            etag='"target"',
            last_modified=now,
        ),
    )
    await cache.set(
        other_key,
        _build_entry(
            path_template="/spotify/playlists/{playlist_id}/tracks",
            etag='"other"',
            last_modified=now,
        ),
    )

    await asyncio.to_thread(invalidator.invalidate, ["playlist-1"])

    assert await cache.get(target_key) is None
    assert await cache.get(other_key) is not None


def test_playlist_list_returns_304_when_unchanged(client: SimpleTestClient) -> None:
    stub = client.app.state.spotify_stub
    stub.playlists = [
        {"id": "playlist-1", "name": "Focus", "tracks": {"total": 10}},
    ]

    worker = client.app.state.playlist_worker
    client._loop.run_until_complete(worker.sync_once())

    initial = client.get("/spotify/playlists")
    assert initial.status_code == 200
    etag = initial.headers.get("etag")
    assert etag is not None

    conditional = client.get("/spotify/playlists", headers={"If-None-Match": etag})
    assert conditional.status_code == 304
    assert conditional.text == ""


def test_playlist_list_busts_cache_on_update_response(
    client: SimpleTestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = client.app.state.spotify_stub
    stub.playlists = [
        {"id": "playlist-1", "name": "Focus", "tracks": {"total": 10}},
    ]

    worker = client.app.state.playlist_worker

    frozen_now = datetime(2024, 1, 1, 12, 0, 0)

    class FrozenDatetime(datetime):  # type: ignore[misc]
        @classmethod
        def utcnow(cls) -> datetime:
            return frozen_now

    monkeypatch.setattr("app.workers.playlist_sync_worker.datetime", FrozenDatetime)

    client._loop.run_until_complete(worker.sync_once())

    initial = client.get("/spotify/playlists")
    assert initial.status_code == 200
    initial_etag = initial.headers.get("etag")
    assert initial_etag is not None

    stub.playlists = [
        {"id": "playlist-1", "name": "Focus Updated", "tracks": {"total": 15}},
    ]
    client._loop.run_until_complete(worker.sync_once())

    refreshed = client.get(
        "/spotify/playlists", headers={"If-None-Match": initial_etag}
    )
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["playlists"][0]["name"] == "Focus Updated"
    assert refreshed.headers.get("etag") != initial_etag
    assert payload != initial.json()
