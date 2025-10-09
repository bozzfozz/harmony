"""Async tests asserting API endpoints respect request deadlines."""

from __future__ import annotations

import time

import pytest
from tests.fixtures.async_client import AsyncDeadlineClient
from tests.helpers import api_path

from app import db, dependencies as deps
from app.workers.playlist_sync_worker import PlaylistSyncWorker


def _install_slow_session_runner(monkeypatch: pytest.MonkeyPatch, delay: float) -> None:
    original_db_run_session = db.run_session

    async def slow_run_session(func, *, factory=None):
        def _with_delay(session):
            time.sleep(delay)
            return func(session)

        return await original_db_run_session(_with_delay, factory=factory)

    monkeypatch.setattr(db, "run_session", slow_run_session)
    monkeypatch.setattr(deps, "run_session", slow_run_session)


@pytest.mark.anyio("asyncio")
async def test_free_import_request_completes_within_deadline(
    async_client_with_deadline: AsyncDeadlineClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deadline = async_client_with_deadline.deadline.default
    delay = deadline * 0.6
    _install_slow_session_runner(monkeypatch, delay)

    async with async_client_with_deadline.within() as (client, elapsed):
        response = await client.post(
            api_path("/imports/free"),
            json={
                "links": [
                    "https://open.spotify.com/playlist/37i9dQZF1DX4JAvHpjipBk",
                ]
            },
        )

    elapsed_seconds = elapsed()
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert elapsed_seconds >= delay
    assert elapsed_seconds < deadline


@pytest.mark.anyio("asyncio")
async def test_manual_sync_request_completes_within_deadline(
    async_client_with_deadline: AsyncDeadlineClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deadline = async_client_with_deadline.deadline.default
    delay = deadline * 0.6
    _install_slow_session_runner(monkeypatch, delay)

    playlist_calls = {"count": 0}

    async def fake_sync_once(self) -> None:  # type: ignore[override]
        playlist_calls["count"] += 1

    monkeypatch.setattr(PlaylistSyncWorker, "sync_once", fake_sync_once, raising=False)

    async with async_client_with_deadline.within() as (client, elapsed):
        response = await client.post(api_path("/sync"))

    elapsed_seconds = elapsed()
    assert response.status_code == 202
    body = response.json()
    assert body["results"]["playlists"] == "completed"
    assert playlist_calls == {"count": 1}
    assert elapsed_seconds >= delay
    assert elapsed_seconds < deadline
