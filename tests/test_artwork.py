import base64
from pathlib import Path
from typing import Any, Dict

import pytest

from app.db import session_scope
from app.models import Download
from app.workers.artwork_worker import ArtworkWorker
from app.workers.sync_worker import SyncWorker
from app.utils import artwork_utils
from app.workers import artwork_worker as artwork_worker_module
from tests.conftest import StubSoulseekClient


@pytest.mark.asyncio
async def test_artwork_worker_fetches_spotify_cover(monkeypatch, tmp_path) -> None:
    audio_path = tmp_path / "track.mp3"
    audio_path.write_bytes(b"audio")

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

    source_cover = tmp_path / "temp.jpg"

    def fake_download(url: str) -> Path:
        source_cover.write_bytes(b"image-bytes")
        return source_cover

    embedded: Dict[str, Path] = {}

    def fake_embed(audio_file: Path, artwork_file: Path) -> None:
        embedded["audio"] = Path(audio_file)
        embedded["artwork"] = Path(artwork_file)

    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", fake_embed)
    monkeypatch.setattr(artwork_worker_module, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_worker_module, "embed_artwork", fake_embed)

    class StubSpotify:
        def get_track_details(self, track_id: str) -> Dict[str, Any]:
            assert track_id == "spotify-track"
            return {
                "album": {
                    "images": [
                        {"url": "http://example.com/cover.jpg", "width": 1000, "height": 1000}
                    ]
                }
            }

    worker = ArtworkWorker(spotify_client=StubSpotify())
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            metadata={},
            spotify_track_id="spotify-track",
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    assert embedded["audio"] == audio_path
    stored_cover = embedded["artwork"]
    assert stored_cover.exists()
    assert stored_cover.parent == audio_path.parent
    assert stored_cover.read_bytes() == b"image-bytes"

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.artwork_status == "done"
        assert Path(refreshed.artwork_path or "") == stored_cover


@pytest.mark.asyncio
async def test_sync_worker_schedules_artwork(tmp_path) -> None:
    audio_path = tmp_path / "sync.mp3"
    audio_path.write_bytes(b"audio")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
            request_payload={
                "spotify_id": "track-123",
                "metadata": {"artwork_url": "http://existing.example/cover.jpg"},
            },
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    class StubArtworkWorker:
        def __init__(self) -> None:
            self.jobs: list[Dict[str, Any]] = []

        async def enqueue(
            self,
            download_id: int | None,
            file_path: str,
            *,
            metadata: Dict[str, Any] | None = None,
            spotify_track_id: str | None = None,
            artwork_url: str | None = None,
        ) -> None:
            self.jobs.append(
                {
                    "download_id": download_id,
                    "file_path": file_path,
                    "metadata": dict(metadata or {}),
                    "spotify_track_id": spotify_track_id,
                    "artwork_url": artwork_url,
                }
            )

    artwork_worker = StubArtworkWorker()
    sync_worker = SyncWorker(
        StubSoulseekClient(),
        artwork_worker=artwork_worker,
    )

    payload = {
        "download_id": download_id,
        "state": "completed",
        "local_path": str(audio_path),
    }

    await sync_worker._handle_download_completion(download_id, payload)

    assert len(artwork_worker.jobs) == 1
    job = artwork_worker.jobs[0]
    assert job["download_id"] == download_id
    assert job["file_path"] == str(audio_path)
    assert job["spotify_track_id"] == "track-123"
    assert job["artwork_url"] == "http://existing.example/cover.jpg"


def test_artwork_endpoint_returns_base64(client, tmp_path) -> None:
    cover_path = tmp_path / "cover.png"
    cover_path.write_bytes(b"png-bytes")

    with session_scope() as session:
        download = Download(
            filename="song.mp3",
            state="completed",
            progress=100.0,
            artwork_status="done",
            artwork_path=str(cover_path),
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    response = client.get(
        f"/soulseek/download/{download_id}/artwork",
        params={"format": "base64"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "done"
    assert payload["mime_type"].startswith("image/")
    assert base64.b64decode(payload["data"]) == b"png-bytes"
