"""Async integration tests verifying DB helpers avoid blocking the event loop."""

from __future__ import annotations

from contextlib import asynccontextmanager
import time

import anyio
from httpx import ASGITransport, AsyncClient
import pytest

from app.db import SessionCallable
from app.dependencies import SessionRunner, get_session_runner
from app.workers.playlist_sync_worker import PlaylistSyncWorker
from tests.helpers import api_path
from tests.simple_client import SimpleTestClient


class TimeBudget:
    """Helper providing an async context manager enforcing a time limit."""

    @asynccontextmanager
    async def limit(self, seconds: float):
        start = time.perf_counter()
        with anyio.fail_after(seconds):
            yield lambda: time.perf_counter() - start


@pytest.fixture
def time_budget() -> TimeBudget:
    return TimeBudget()


@pytest.fixture
async def async_client(client: SimpleTestClient) -> AsyncClient:
    transport = ASGITransport(app=client.app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as http_client:
        yield http_client


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _slow_runner(delay: float, runner: SessionRunner) -> SessionRunner:
    async def _wrapper(func: SessionCallable[object]) -> object:
        def _delayed(session):
            time.sleep(delay)
            return func(session)

        return await runner(_delayed)

    return _wrapper


@pytest.mark.anyio("asyncio")
async def test_free_import_uses_async_session(
    client: SimpleTestClient,
    async_client: AsyncClient,
    time_budget: TimeBudget,
) -> None:
    delay = 0.2
    original_runner = get_session_runner()
    client.app.dependency_overrides[get_session_runner] = lambda: _slow_runner(
        delay, original_runner
    )

    try:
        async with time_budget.limit(0.75) as elapsed:
            response = await async_client.post(
                api_path("/imports/free"),
                json={
                    "links": [
                        "https://open.spotify.com/playlist/37i9dQZF1DX4JAvHpjipBk",
                    ]
                },
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert elapsed() >= delay
    finally:
        client.app.dependency_overrides.pop(get_session_runner, None)


@pytest.mark.anyio("asyncio")
async def test_manual_sync_checks_credentials_off_thread(
    client: SimpleTestClient,
    async_client: AsyncClient,
    time_budget: TimeBudget,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delay = 0.2
    original_runner = get_session_runner()
    client.app.dependency_overrides[get_session_runner] = lambda: _slow_runner(
        delay, original_runner
    )

    playlist_calls = {"count": 0}

    async def fake_sync_once(self) -> None:  # type: ignore[override]
        playlist_calls["count"] += 1

    monkeypatch.setattr(PlaylistSyncWorker, "sync_once", fake_sync_once, raising=False)

    try:
        async with time_budget.limit(0.75) as elapsed:
            response = await async_client.post(api_path("/sync"))
        assert response.status_code == 202
        body = response.json()
        assert body["results"]["playlists"] == "completed"
        assert playlist_calls == {"count": 1}
        assert elapsed() >= delay
    finally:
        client.app.dependency_overrides.pop(get_session_runner, None)


@pytest.mark.anyio("asyncio")
async def test_download_queue_uses_async_session(
    client: SimpleTestClient,
    async_client: AsyncClient,
    time_budget: TimeBudget,
) -> None:
    delay = 0.2
    original_runner = get_session_runner()
    client.app.dependency_overrides[get_session_runner] = lambda: _slow_runner(
        delay, original_runner
    )

    payload = {
        "username": "tester",
        "files": [{"filename": "queued.mp3", "size": 1024}],
    }

    try:
        async with time_budget.limit(0.75) as elapsed:
            response = await async_client.post(api_path("/download"), json=payload)
        assert response.status_code == 202
        assert elapsed() >= delay
    finally:
        client.app.dependency_overrides.pop(get_session_runner, None)


@pytest.mark.anyio("asyncio")
async def test_download_cancel_uses_async_session(
    client: SimpleTestClient,
    async_client: AsyncClient,
    time_budget: TimeBudget,
) -> None:
    payload = {
        "username": "tester",
        "files": [{"filename": "cancel.mp3", "size": 256}],
    }

    start_response = await async_client.post(api_path("/download"), json=payload)
    download_id = start_response.json()["download_id"]

    delay = 0.2
    original_runner = get_session_runner()
    client.app.dependency_overrides[get_session_runner] = lambda: _slow_runner(
        delay, original_runner
    )

    try:
        async with time_budget.limit(0.75) as elapsed:
            response = await async_client.delete(api_path(f"/download/{download_id}"))
        assert response.status_code == 200
        assert elapsed() >= delay
    finally:
        client.app.dependency_overrides.pop(get_session_runner, None)


@pytest.mark.anyio("asyncio")
async def test_download_retry_uses_async_session(
    client: SimpleTestClient,
    async_client: AsyncClient,
    time_budget: TimeBudget,
) -> None:
    payload = {
        "username": "tester",
        "files": [{"filename": "retry.mp3", "size": 512}],
    }

    start_response = await async_client.post(api_path("/download"), json=payload)
    download_id = start_response.json()["download_id"]
    cancel_response = await async_client.delete(api_path(f"/download/{download_id}"))
    assert cancel_response.status_code == 200

    delay = 0.2
    original_runner = get_session_runner()
    client.app.dependency_overrides[get_session_runner] = lambda: _slow_runner(
        delay, original_runner
    )

    try:
        async with time_budget.limit(0.75) as elapsed:
            response = await async_client.post(api_path(f"/download/{download_id}/retry"))
        assert response.status_code == 202
        assert elapsed() >= delay
    finally:
        client.app.dependency_overrides.pop(get_session_runner, None)
