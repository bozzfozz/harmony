from __future__ import annotations

import asyncio
import time

import pytest

from app.workers.playlist_sync_worker import PlaylistSyncWorker


class _SlowSpotifyClient:
    def __init__(self) -> None:
        self.calls = 0

    def get_user_playlists(self) -> list[dict[str, object]]:
        self.calls += 1
        time.sleep(0.05)
        return []


@pytest.mark.asyncio
async def test_playlist_sync_worker_yields_control_during_fetch() -> None:
    client = _SlowSpotifyClient()
    worker = PlaylistSyncWorker(client, interval_seconds=0.1)

    sync_finished = asyncio.Event()
    ticker_ran = asyncio.Event()

    async def ticker() -> None:
        try:
            while not sync_finished.is_set():
                ticker_ran.set()
                await asyncio.sleep(0)
        finally:  # pragma: no cover - defensive guard
            sync_finished.set()

    ticker_task = asyncio.create_task(ticker())
    sync_task = asyncio.create_task(worker.sync_once())

    await asyncio.wait_for(ticker_ran.wait(), timeout=0.2)

    await sync_task
    sync_finished.set()
    await ticker_task

    assert client.calls == 1
