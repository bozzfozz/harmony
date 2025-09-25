from __future__ import annotations

import sys
import types
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
async def test_spotify_artwork_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "track.mp3"
    audio_path.write_bytes(b"audio-bytes")

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

    stored: Dict[str, Any] = {}

    def fake_download(url: str, target: Path) -> Path:
        stored["download_url"] = url
        destination = Path(target)
        if not destination.suffix:
            destination = destination.with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"image-bytes")
        stored["downloaded_path"] = destination
        return destination

    def fake_embed(audio_file: Path, artwork_file: Path) -> None:
        stored["embedded"] = (Path(audio_file), Path(artwork_file))

    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", fake_embed)

    class StubSpotify:
        def __init__(self) -> None:
            self.album_calls: list[str] = []
            self.track_calls: list[str] = []

        def get_album_details(self, album_id: str) -> Dict[str, Any]:
            self.album_calls.append(album_id)
            return {
                "images": [
                    {"url": "http://example.com/medium.jpg", "width": 640, "height": 640},
                    {"url": "http://example.com/large.jpg", "width": 2000, "height": 2000},
                ]
            }

        def get_track_details(self, track_id: str) -> Dict[str, Any]:
            self.track_calls.append(track_id)
            return {"album": {"id": "album-123"}}

    worker = ArtworkWorker(spotify_client=StubSpotify(), storage_directory=tmp_path / "artwork")
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            metadata={},
            spotify_track_id="track-xyz",
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    stored_path = stored["downloaded_path"]
    assert stored["download_url"] == "http://example.com/large.jpg"
    assert stored["embedded"] == (audio_path, stored_path)
    assert stored_path.exists()

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is True
        assert refreshed.artwork_status == "done"
        assert refreshed.spotify_album_id == "album-123"
        assert Path(refreshed.artwork_path or "") == stored_path


def _install_mutagen_stubs(monkeypatch: pytest.MonkeyPatch, tracker: Dict[str, Any]) -> None:
    module_mutagen = types.ModuleType("mutagen")

    class DummyID3NoHeaderError(Exception):
        pass

    class DummyID3Factory:
        def __init__(self) -> None:
            self._first = True

        def __call__(self, path: Path | None = None) -> "DummyID3":
            tracker.setdefault("id3_calls", []).append(path)
            if path is not None and self._first:
                self._first = False
                raise DummyID3NoHeaderError()
            return DummyID3()

    class DummyID3:
        def __init__(self) -> None:
            self.tags: Dict[str, Any] = {}

        def delall(self, key: str) -> None:
            tracker["id3_del"] = key

        def add(self, apic: "DummyAPIC") -> None:
            tracker["id3_apic"] = apic.params

        def save(self, path: Path) -> None:
            tracker["id3_saved"] = path

    class DummyAPIC:
        def __init__(self, **params: Any) -> None:
            self.params = params

    module_id3 = types.ModuleType("mutagen.id3")
    module_id3.APIC = DummyAPIC
    module_id3.ID3 = DummyID3Factory()
    module_id3.ID3NoHeaderError = DummyID3NoHeaderError

    class DummyPicture:
        def __init__(self) -> None:
            self.type = None
            self.mime = None
            self.desc = None
            self.data = None

    class DummyFLAC:
        def __init__(self, path: Path) -> None:
            tracker["flac_path"] = path
            self.pictures: list[DummyPicture] = []

        def clear_pictures(self) -> None:
            tracker["flac_cleared"] = True

        def add_picture(self, picture: DummyPicture) -> None:
            tracker["flac_picture"] = {
                "mime": picture.mime,
                "desc": picture.desc,
                "data": picture.data,
            }

        def save(self) -> None:
            tracker["flac_saved"] = True

    module_flac = types.ModuleType("mutagen.flac")
    module_flac.FLAC = DummyFLAC
    module_flac.Picture = DummyPicture

    class DummyMP4Cover:
        FORMAT_PNG = 1
        FORMAT_JPEG = 2

        def __init__(self, data: bytes, imageformat: int) -> None:
            tracker["mp4_cover"] = {"data": data, "format": imageformat}

    class DummyMP4:
        def __init__(self, path: Path) -> None:
            tracker["mp4_path"] = path
            self.tags: Dict[str, Any] = {}

        def save(self) -> None:
            tracker["mp4_saved"] = True

    module_mp4 = types.ModuleType("mutagen.mp4")
    module_mp4.MP4 = DummyMP4
    module_mp4.MP4Cover = DummyMP4Cover

    module_mutagen.id3 = module_id3
    module_mutagen.flac = module_flac
    module_mutagen.mp4 = module_mp4

    monkeypatch.setitem(sys.modules, "mutagen", module_mutagen)
    monkeypatch.setitem(sys.modules, "mutagen.id3", module_id3)
    monkeypatch.setitem(sys.modules, "mutagen.flac", module_flac)
    monkeypatch.setitem(sys.modules, "mutagen.mp4", module_mp4)


def test_embed_mp3_flac_m4a(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tracker: Dict[str, Any] = {}
    _install_mutagen_stubs(monkeypatch, tracker)

    art_path = tmp_path / "cover.jpg"
    art_path.write_bytes(b"image-bytes")

    mp3_file = tmp_path / "song.mp3"
    mp3_file.write_bytes(b"mp3")
    flac_file = tmp_path / "song.flac"
    flac_file.write_bytes(b"flac")
    m4a_file = tmp_path / "song.m4a"
    m4a_file.write_bytes(b"m4a")

    artwork_utils.embed_artwork(mp3_file, art_path)
    assert tracker["id3_del"] == "APIC"
    assert tracker["id3_saved"] == mp3_file
    assert tracker["id3_apic"]["mime"].startswith("image/")

    tracker.clear()
    _install_mutagen_stubs(monkeypatch, tracker)
    artwork_utils.embed_artwork(flac_file, art_path)
    assert tracker["flac_path"] == flac_file
    assert tracker.get("flac_cleared") is True
    assert tracker["flac_saved"] is True
    assert tracker["flac_picture"]["mime"].startswith("image/")

    tracker.clear()
    _install_mutagen_stubs(monkeypatch, tracker)
    artwork_utils.embed_artwork(m4a_file, art_path)
    assert tracker["mp4_path"] == m4a_file
    assert tracker["mp4_saved"] is True
    assert tracker["mp4_cover"]["format"] == 2


def test_no_artwork_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client,
) -> None:
    audio_path = tmp_path / "missing.mp3"
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

    def raise_no_art(*args: Any, **kwargs: Any) -> Path:
        raise RuntimeError("no art")

    monkeypatch.setattr(artwork_utils, "download_artwork", raise_no_art)
    monkeypatch.setattr(artwork_utils, "embed_artwork", lambda *_: None)

    async def process() -> None:
        worker = ArtworkWorker(storage_directory=tmp_path / "artwork")
        await worker.start()
        try:
            await worker.enqueue(download_id, str(audio_path), metadata={})
            await worker.wait_for_pending()
        finally:
            await worker.stop()

    client._loop.run_until_complete(process())

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is False
        assert refreshed.artwork_status == "failed"

    response = client.get(f"/soulseek/download/{download_id}/artwork")
    assert response.status_code == 404


def test_refresh_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, client) -> None:
    audio_path = tmp_path / "refresh.mp3"
    audio_path.write_bytes(b"audio")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
            artwork_status="done",
            artwork_path=str(tmp_path / "old.jpg"),
            has_artwork=True,
            request_payload={
                "metadata": {"artwork_url": "http://example.com/original.jpg"},
                "album": {"id": "album-999"},
            },
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    jobs: list[Dict[str, Any]] = []

    class StubArtworkWorker:
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
            jobs.append(
                {
                    "download_id": download_id,
                    "file_path": file_path,
                    "metadata": dict(metadata or {}),
                    "spotify_track_id": spotify_track_id,
                    "spotify_album_id": spotify_album_id,
                    "artwork_url": artwork_url,
                }
            )

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    client.app.state.artwork_worker = StubArtworkWorker()

    response = client.post(f"/soulseek/download/{download_id}/artwork/refresh")
    assert response.status_code == 202
    assert len(jobs) == 1
    job = jobs[0]
    assert job["download_id"] == download_id
    assert job["file_path"] == str(audio_path)
    assert job["metadata"].get("artwork_url") == "http://example.com/original.jpg"
    assert job["spotify_album_id"] == "album-999"

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.artwork_status == "pending"
        assert refreshed.has_artwork is False
        assert refreshed.spotify_album_id == "album-999"


@pytest.mark.asyncio
async def test_sync_worker_schedules_artwork(tmp_path: Path) -> None:
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

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.spotify_track_id == "track-123"
        assert refreshed.spotify_album_id == "album-999"


def test_artwork_endpoint_returns_image(client, tmp_path: Path) -> None:
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
