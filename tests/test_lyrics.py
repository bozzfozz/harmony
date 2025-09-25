from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.db import session_scope
from app.models import Download
from app.workers.lyrics_worker import LyricsWorker
from app.workers.sync_worker import SyncWorker
from tests.conftest import StubSoulseekClient


@pytest.mark.asyncio
async def test_lyrics_worker_generates_lrc_file(tmp_path) -> None:
    audio_path = tmp_path / "track.mp3"
    audio_path.write_bytes(b"dummy")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    async def stub_provider(track_info: dict[str, Any]) -> str:
        return "Line one\nLine two"

    worker = LyricsWorker(lyrics_provider=stub_provider)
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            {"title": "Test Track", "artist": "Tester"},
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    lrc_path = audio_path.with_suffix(".lrc")
    assert lrc_path.exists()
    content = lrc_path.read_text(encoding="utf-8")
    assert "Test Track" in content
    assert "[00:00." in content

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.lyrics_status == "done"
        assert Path(refreshed.lyrics_path or "") == lrc_path


@pytest.mark.asyncio
async def test_sync_worker_schedules_lyrics_generation(tmp_path) -> None:
    audio_path = tmp_path / "sync.flac"
    audio_path.write_bytes(b"data")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
            request_payload={"metadata": {"title": "Sync Song"}},
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    async def stub_provider(track_info: dict[str, Any]) -> str:
        return "Only line"

    lyrics_worker = LyricsWorker(lyrics_provider=stub_provider)
    await lyrics_worker.start()
    try:
        sync_worker = SyncWorker(StubSoulseekClient(), lyrics_worker=lyrics_worker)
        payload = {
            "download_id": download_id,
            "state": "completed",
            "local_path": str(audio_path),
            "title": "Sync Song",
            "artist": "The Syncs",
        }
        await sync_worker._handle_download_completion(download_id, payload)
        await lyrics_worker.wait_for_pending()
    finally:
        await lyrics_worker.stop()

    lrc_path = audio_path.with_suffix(".lrc")
    assert lrc_path.exists()
    assert "Sync Song" in lrc_path.read_text(encoding="utf-8")


def test_lyrics_endpoint_returns_content(client, tmp_path) -> None:
    lrc_path = tmp_path / "endpoint.lrc"
    lrc_path.write_text("[00:00.00]Hello", encoding="utf-8")

    with session_scope() as session:
        download = Download(
            filename="endpoint.mp3",
            state="completed",
            progress=100.0,
            lyrics_status="done",
            lyrics_path=str(lrc_path),
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    response = client.get(f"/soulseek/download/{download_id}/lyrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "Hello" in response._body.decode("utf-8")
