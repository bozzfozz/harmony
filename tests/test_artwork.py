from pathlib import Path
from typing import Any, Dict

import pytest

from app.db import session_scope
from app.models import Download
from app.utils import artwork_utils
from app.workers.artwork_worker import ArtworkWorker
from app.workers.sync_worker import SyncWorker
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

    stored_files: Dict[str, Path] = {}

    def fake_download(url: str, target: Path) -> Path:
        destination = Path(target)
        if not destination.suffix:
            destination = destination.with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"image-bytes")
        stored_files["downloaded"] = destination
        return destination

    def fake_embed(audio_file: Path, artwork_file: Path) -> None:
        stored_files["audio"] = Path(audio_file)
        stored_files["artwork"] = Path(artwork_file)

    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", fake_embed)

    class StubSpotify:
        def get_album_details(self, album_id: str) -> Dict[str, Any]:
            assert album_id == "album-123"
            return {
                "images": [
                    {"url": "http://example.com/cover.jpg", "width": 2000, "height": 2000},
                ]
            }

        def get_track_details(self, track_id: str) -> Dict[str, Any]:
            return {}

    artwork_dir = tmp_path / "artwork"
    worker = ArtworkWorker(spotify_client=StubSpotify(), storage_directory=artwork_dir)
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            metadata={},
            spotify_album_id="album-123",
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    stored_cover = stored_files["artwork"]
    assert stored_files["audio"] == audio_path
    assert stored_cover.exists()
    assert stored_cover.parent == artwork_dir.resolve()
    assert stored_cover.read_bytes() == b"image-bytes"

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is True
        assert refreshed.artwork_status == "done"
        assert Path(refreshed.artwork_path or "") == stored_cover


@pytest.mark.asyncio
async def test_artwork_worker_marks_failure(monkeypatch, tmp_path) -> None:
    audio_path = tmp_path / "failure.mp3"
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

    def fake_download(url: str, target: Path) -> Path:
        raise RuntimeError("no artwork")

    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", lambda *_: None)

    worker = ArtworkWorker(storage_directory=tmp_path / "artwork")
    await worker.start()
    try:
        await worker.enqueue(download_id, str(audio_path), metadata={})
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is False
        assert refreshed.artwork_status == "failed"
        assert refreshed.artwork_path is None


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
                "album": {"id": "album-999"},
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
            spotify_album_id: str | None = None,
            artwork_url: str | None = None,
        ) -> None:
            self.jobs.append(
                {
                    "download_id": download_id,
                    "file_path": file_path,
                    "metadata": dict(metadata or {}),
                    "spotify_track_id": spotify_track_id,
                    "spotify_album_id": spotify_album_id,
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
    assert job["spotify_album_id"] == "album-999"
    assert job["artwork_url"] == "http://existing.example/cover.jpg"


def test_artwork_endpoint_returns_image(client, tmp_path) -> None:
    cover_path = tmp_path / "cover.png"
    cover_path.write_bytes(b"png-bytes")

    with session_scope() as session:
        download = Download(
            filename="song.mp3",
            state="completed",
            progress=100.0,
            artwork_status="done",
            artwork_path=str(cover_path),
            has_artwork=True,
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    response = client.get(f"/soulseek/download/{download_id}/artwork")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")
    assert response._body == b"png-bytes"
