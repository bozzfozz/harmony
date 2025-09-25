from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from app.db import session_scope
from app.models import Download
from app.workers.lyrics_worker import LyricsWorker
from app.workers.sync_worker import SyncWorker
from tests.conftest import StubSoulseekClient


class StubSpotifyClient:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_track_details(self, track_id: str) -> Dict[str, Any]:
        self.calls.append(track_id)
        return dict(self.payload)


@pytest.mark.asyncio
async def test_lyrics_worker_generates_lrc_file_from_spotify(tmp_path) -> None:
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

    spotify_payload = {
        "name": "Test Track",
        "artists": [{"name": "Tester"}],
        "album": {"name": "Album"},
        "duration_ms": 60000,
        "sync_lyrics": [
            {"start": 0, "text": "Line one"},
            {"start": 15000, "text": "Line two"},
        ],
    }
    spotify_client = StubSpotifyClient(spotify_payload)

    worker = LyricsWorker(
        spotify_client=spotify_client,
        fallback_provider=lambda _: None,
    )
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            {
                "title": "Test Track",
                "artist": "Tester",
                "album": "Album",
                "spotify_track_id": "spotify:track:123",
            },
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    lrc_path = audio_path.with_suffix(".lrc")
    assert lrc_path.exists()
    content = lrc_path.read_text(encoding="utf-8")
    assert "Test Track" in content
    assert "[00:15.00]Line two" in content
    assert spotify_client.calls == ["spotify:track:123"]

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.lyrics_status == "done"
        assert refreshed.has_lyrics is True
        assert Path(refreshed.lyrics_path or "") == lrc_path


@pytest.mark.asyncio
async def test_lyrics_worker_sets_has_lyrics_false_when_missing(tmp_path) -> None:
    audio_path = tmp_path / "missing.mp3"
    audio_path.write_bytes(b"data")

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

    async def empty_provider(_: Dict[str, Any]) -> None:
        return None

    worker = LyricsWorker(
        spotify_client=None,
        fallback_provider=empty_provider,
    )
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            {"title": "Missing", "artist": "Silence"},
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_lyrics is False
        assert (refreshed.lyrics_path or "") == ""
        assert refreshed.lyrics_status == "failed"


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

    async def stub_provider(track_info: Dict[str, Any]) -> Dict[str, Any]:
        return {"lyrics": "Only line", "title": track_info.get("title", "")}

    lyrics_worker = LyricsWorker(
        spotify_client=None,
        fallback_provider=stub_provider,
    )
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
            has_lyrics=True,
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


def test_refresh_endpoint_triggers_worker(client, tmp_path) -> None:
    audio_path = tmp_path / "refresh.mp3"
    audio_path.write_text("hi", encoding="utf-8")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
            request_payload={"metadata": {"title": "Refresh Song", "artist": "Band"}},
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    response = client.post(f"/soulseek/download/{download_id}/lyrics/refresh")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"

    # The StubLyricsWorker captures enqueued jobs
    worker = client.app.state.lyrics_worker  # type: ignore[attr-defined]
    assert worker.jobs
    queued_id, path, track_info = worker.jobs[-1]
    assert queued_id == download_id
    assert path == str(audio_path)
    assert track_info["title"] == "Refresh Song"

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.lyrics_status == "pending"
        assert refreshed.has_lyrics is False
