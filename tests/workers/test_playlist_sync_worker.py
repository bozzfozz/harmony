from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager

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


@pytest.mark.asyncio
async def test_playlist_sync_worker_offloads_db_work(monkeypatch: pytest.MonkeyPatch) -> None:
    main_thread = threading.current_thread()
    session_threads: list[threading.Thread] = []

    class DummySession:
        def __init__(self) -> None:
            self.store: dict[str, object] = {}

        def get(self, _model: object, key: str) -> object | None:
            return self.store.get(key)

        def add(self, playlist: object) -> None:
            playlist_id = getattr(playlist, "id", None)
            if playlist_id is not None:
                self.store[str(playlist_id)] = playlist

    @contextmanager
    def fake_session_scope() -> DummySession:
        session_threads.append(threading.current_thread())
        yield DummySession()

    monkeypatch.setattr(
        "app.workers.playlist_sync_worker.session_scope",
        fake_session_scope,
    )

    client_payload = [{"id": "abc123", "name": "Test Playlist", "tracks": {"total": 3}}]

    class _Client:
        def get_user_playlists(self) -> list[dict[str, object]]:
            return client_payload

    worker = PlaylistSyncWorker(_Client(), interval_seconds=0.1)

    original_to_thread = asyncio.to_thread
    to_thread_calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    async def spy_to_thread(func: object, /, *args: object, **kwargs: object) -> object:
        to_thread_calls.append((func, args, kwargs))
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)

    await worker.sync_once()

    assert any(
        getattr(call[0], "__name__", "") == "_persist_playlists" for call in to_thread_calls
    ), "Database persistence should run via asyncio.to_thread"
    assert session_threads, "session_scope should be invoked"
    assert all(thread is not main_thread for thread in session_threads)
