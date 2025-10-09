from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest
from tests.conftest import StubSoulseekClient

import app.workers.artwork_worker as artwork_worker
from app.config import ArtworkConfig, ArtworkFallbackConfig, ArtworkPostProcessingConfig
from app.db import session_scope
from app.models import Download
from app.utils import artwork_utils
from app.workers.artwork_worker import (
    ArtworkJob,
    ArtworkProcessingResult,
    ArtworkWorker,
)
from app.workers.sync_worker import SyncWorker


def _make_artwork_config(
    base_dir: Path,
    *,
    fallback_enabled: bool = False,
    fallback_timeout: float = 5.0,
    min_edge: int = 600,
    min_bytes: int = 120_000,
    post_processing_enabled: bool = False,
    post_processing_hooks: tuple[str, ...] = (),
) -> ArtworkConfig:
    provider = "musicbrainz" if fallback_enabled else "none"
    return ArtworkConfig(
        directory=str(base_dir),
        timeout_seconds=5.0,
        max_bytes=5 * 1024 * 1024,
        concurrency=1,
        min_edge=min_edge,
        min_bytes=min_bytes,
        fallback=ArtworkFallbackConfig(
            enabled=fallback_enabled,
            provider=provider,
            timeout_seconds=fallback_timeout,
            max_bytes=5 * 1024 * 1024,
        ),
        post_processing=ArtworkPostProcessingConfig(
            enabled=post_processing_enabled,
            hooks=post_processing_hooks,
        ),
    )


@pytest.mark.asyncio
async def test_spotify_artwork_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    def fake_download(url: str, target: Path, **_: Any) -> Path:
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
    monkeypatch.setattr(artwork_utils, "extract_embed_info", lambda *_: None)

    class StubSpotify:
        def __init__(self) -> None:
            self.album_calls: list[str] = []
            self.track_calls: list[str] = []

        def get_album_details(self, album_id: str) -> Dict[str, Any]:
            self.album_calls.append(album_id)
            return {
                "images": [
                    {
                        "url": "http://example.com/medium.jpg",
                        "width": 640,
                        "height": 640,
                    },
                    {
                        "url": "http://example.com/large.jpg",
                        "width": 2000,
                        "height": 2000,
                    },
                ]
            }

        def get_track_details(self, track_id: str) -> Dict[str, Any]:
            self.track_calls.append(track_id)
            return {"album": {"id": "album-123"}}

    worker = ArtworkWorker(
        spotify_client=StubSpotify(),
        storage_directory=tmp_path / "artwork",
        config=_make_artwork_config(tmp_path / "artwork"),
    )
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
    assert stored_path.name.endswith("_original.jpg")

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is True
        assert refreshed.artwork_status == "done"
        assert refreshed.spotify_album_id == "album-123"
        assert Path(refreshed.artwork_path or "") == stored_path


@pytest.mark.asyncio
async def test_post_processing_hook_invoked_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio_path = tmp_path / "hook.mp3"
    audio_path.write_bytes(b"audio")

    async def fake_collect(self: ArtworkWorker, *_: Any, **__: Any) -> list[str]:
        return ["http://example.com/post.jpg"]

    def fake_download(url: str, target: Path, **_: Any) -> Path:
        destination = target.with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"img")
        return destination

    def fake_embed(audio_file: Path, artwork_file: Path) -> None:
        assert audio_file == audio_path
        assert artwork_file.exists()

    monkeypatch.setattr(
        ArtworkWorker, "_collect_candidate_urls", fake_collect, raising=False
    )
    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", fake_embed)
    monkeypatch.setattr(artwork_utils, "extract_embed_info", lambda *_: None)

    calls: list[tuple[str, Path | None]] = []

    async def hook(job: "ArtworkJob", result: "ArtworkProcessingResult") -> None:
        calls.append((job.file_path, result.artwork_path))

    config = _make_artwork_config(
        tmp_path / "artwork",
        post_processing_enabled=True,
    )
    worker = ArtworkWorker(
        storage_directory=tmp_path / "artwork",
        config=config,
        post_processing_hooks=[hook],
    )
    await worker.start()
    try:
        await worker.enqueue(None, str(audio_path), metadata={})
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    assert len(calls) == 1
    call_job_path, call_result_path = calls[0]
    assert call_job_path == str(audio_path)
    assert call_result_path is not None and call_result_path.exists()


@pytest.mark.asyncio
async def test_post_processing_hook_failure_logs_and_continues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio_path = tmp_path / "hook-fail.mp3"
    audio_path.write_bytes(b"audio")

    async def fake_collect(self: ArtworkWorker, *_: Any, **__: Any) -> list[str]:
        return ["http://example.com/post.jpg"]

    def fake_download(url: str, target: Path, **_: Any) -> Path:
        destination = target.with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"img")
        return destination

    monkeypatch.setattr(
        ArtworkWorker, "_collect_candidate_urls", fake_collect, raising=False
    )
    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", lambda *_: None)
    monkeypatch.setattr(artwork_utils, "extract_embed_info", lambda *_: None)

    calls: list[str] = []
    logged: list[dict[str, Any]] = []

    def fake_exception(self: Any, message: str, *args: Any, **kwargs: Any) -> None:
        logged.append({"message": message, "extra": kwargs.get("extra")})

    monkeypatch.setattr(
        artwork_worker.logger,
        "exception",
        types.MethodType(fake_exception, artwork_worker.logger),
    )

    def failing_hook(job: "ArtworkJob", _: "ArtworkProcessingResult") -> None:
        calls.append("first")
        raise RuntimeError("boom")

    async def succeeding_hook(
        job: "ArtworkJob", result: "ArtworkProcessingResult"
    ) -> None:
        calls.append("second")
        assert result.artwork_path is not None

    config = _make_artwork_config(
        tmp_path / "artwork",
        post_processing_enabled=True,
    )
    worker = ArtworkWorker(
        storage_directory=tmp_path / "artwork",
        config=config,
        post_processing_hooks=[failing_hook, succeeding_hook],
    )
    await worker.start()
    try:
        await worker.enqueue(None, str(audio_path), metadata={})
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    assert calls == ["first", "second"]
    assert len(logged) == 1
    assert "post-processing hook failed" in logged[0]["message"]


@pytest.mark.asyncio
async def test_post_processing_hooks_respect_disable_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio_path = tmp_path / "hook-disabled.mp3"
    audio_path.write_bytes(b"audio")

    async def fake_collect(self: ArtworkWorker, *_: Any, **__: Any) -> list[str]:
        return ["http://example.com/post.jpg"]

    def fake_download(url: str, target: Path, **_: Any) -> Path:
        destination = target.with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"img")
        return destination

    monkeypatch.setattr(
        ArtworkWorker, "_collect_candidate_urls", fake_collect, raising=False
    )
    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", lambda *_: None)
    monkeypatch.setattr(artwork_utils, "extract_embed_info", lambda *_: None)

    calls: list[str] = []

    def hook(job: "ArtworkJob", result: "ArtworkProcessingResult") -> None:
        calls.append(job.file_path)

    config = _make_artwork_config(
        tmp_path / "artwork",
        post_processing_enabled=False,
    )
    worker = ArtworkWorker(
        storage_directory=tmp_path / "artwork",
        config=config,
        post_processing_hooks=[hook],
    )
    await worker.start()
    try:
        await worker.enqueue(None, str(audio_path), metadata={})
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    assert calls == []


def _install_mutagen_stubs(
    monkeypatch: pytest.MonkeyPatch, tracker: Dict[str, Any]
) -> None:
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


def test_artwork_utils_lowres_detection() -> None:
    small = {"width": 320, "height": 320, "bytes": 80_000}
    large = {"width": 1500, "height": 1500, "bytes": 400_000}
    unknown_small = {"width": 0, "height": 0, "bytes": 120_000}
    unknown_large = {"width": 0, "height": 0, "bytes": 220_000}

    assert artwork_utils.is_low_res(small, min_edge=1000, min_bytes=150_000) is True
    assert artwork_utils.is_low_res(large, min_edge=1000, min_bytes=150_000) is False
    assert (
        artwork_utils.is_low_res(unknown_small, min_edge=1000, min_bytes=150_000)
        is True
    )
    assert (
        artwork_utils.is_low_res(unknown_large, min_edge=1000, min_bytes=150_000)
        is False
    )


@pytest.mark.asyncio
async def test_embed_replace_when_lowres_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "lowres.mp3"
    audio_path.write_bytes(b"audio")
    existing_art = tmp_path / "old.jpg"
    existing_art.write_bytes(b"old")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
            artwork_status="pending",
            artwork_path=str(existing_art),
            has_artwork=True,
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    stored: Dict[str, Any] = {}

    monkeypatch.setattr(
        artwork_utils,
        "extract_embed_info",
        lambda *_: {"width": 300, "height": 300, "bytes": 50_000},
    )
    monkeypatch.setattr(
        artwork_utils, "fetch_spotify_artwork", lambda *_: "http://img/cover.jpg"
    )

    def fake_download(url: str, target: Path, **_: Any) -> Path:
        destination = target.with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"new-art")
        stored["downloaded"] = destination
        stored["url"] = url
        return destination

    def fake_embed(audio_file: Path, artwork_file: Path) -> None:
        stored["embedded"] = (Path(audio_file), Path(artwork_file))

    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", fake_embed)

    worker = ArtworkWorker(
        storage_directory=tmp_path / "artwork",
        config=_make_artwork_config(tmp_path / "artwork", min_edge=800),
    )
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            metadata={
                "artwork_url": "http://example.com/cover.jpg",
                "artist": "Artist",
                "album": "Album",
            },
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    assert stored.get("embedded") == (audio_path, stored.get("downloaded"))

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is True
        assert refreshed.artwork_status == "done"
        assert Path(refreshed.artwork_path or "") == stored["downloaded"]
        assert refreshed.artwork_url == "http://example.com/cover.jpg"


@pytest.mark.asyncio
async def test_no_replace_when_hires_and_no_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "hires.mp3"
    audio_path.write_bytes(b"audio")
    existing_art = tmp_path / "existing.jpg"
    existing_art.write_bytes(b"art")

    with session_scope() as session:
        download = Download(
            filename=str(audio_path),
            state="completed",
            progress=100.0,
            artwork_status="pending",
            artwork_path=str(existing_art),
            has_artwork=True,
        )
        session.add(download)
        session.commit()
        session.refresh(download)
        download_id = download.id

    monkeypatch.setattr(
        artwork_utils,
        "extract_embed_info",
        lambda *_: {"width": 1600, "height": 1600, "bytes": 400_000},
    )
    download_calls: list[str] = []

    def unexpected_download(*_a: Any, **_k: Any) -> Path:
        download_calls.append("download")
        raise AssertionError(
            "download_artwork should not run for high-resolution embeds"
        )

    def unexpected_embed(*_a: Any, **_k: Any) -> None:
        download_calls.append("embed")
        raise AssertionError("embed_artwork should not run for high-resolution embeds")

    monkeypatch.setattr(artwork_utils, "download_artwork", unexpected_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", unexpected_embed)

    worker = ArtworkWorker(
        storage_directory=tmp_path / "artwork",
        config=_make_artwork_config(tmp_path / "artwork", min_edge=800),
    )
    await worker.start()
    try:
        await worker.enqueue(download_id, str(audio_path), metadata={})
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    assert download_calls == []

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is True
        assert refreshed.artwork_path == str(existing_art)


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
    monkeypatch.setattr(artwork_utils, "extract_embed_info", lambda *_: None)

    async def process() -> None:
        worker = ArtworkWorker(
            storage_directory=tmp_path / "artwork",
            config=_make_artwork_config(tmp_path / "artwork"),
        )
        await worker.start()
        try:
            await worker.enqueue(
                download_id,
                str(audio_path),
                metadata={"spotify_album_id": "album-poststep"},
            )
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


def test_refresh_endpoint_enqueues(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, client
) -> None:
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
            refresh: bool = False,
        ) -> None:
            jobs.append(
                {
                    "download_id": download_id,
                    "file_path": file_path,
                    "metadata": dict(metadata or {}),
                    "spotify_track_id": spotify_track_id,
                    "spotify_album_id": spotify_album_id,
                    "artwork_url": artwork_url,
                    "refresh": refresh,
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
    assert job["refresh"] is True

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
            refresh: bool = False,
        ) -> None:
            self.jobs.append(
                {
                    "download_id": download_id,
                    "file_path": file_path,
                    "metadata": dict(metadata or {}),
                    "spotify_track_id": spotify_track_id,
                    "spotify_album_id": spotify_album_id,
                    "artwork_url": artwork_url,
                    "refresh": refresh,
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
    assert job["spotify_track_id"] == "track-123"
    assert job["spotify_album_id"] == "album-999"
    assert job["artwork_url"] == "http://existing.example/cover.jpg"
    assert job["refresh"] is False

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert job["file_path"] == refreshed.filename
        assert refreshed.organized_path == refreshed.filename
        assert Path(refreshed.organized_path).exists()
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


@pytest.mark.asyncio
async def test_fallback_disabled_no_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio_path = tmp_path / "no-fallback.mp3"
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

    calls: List[str] = []

    def fake_fetch(*_args: Any, **_kwargs: Any) -> str:
        calls.append("fallback")
        return "https://coverartarchive.org/release-group/xyz/front"

    monkeypatch.setattr(artwork_utils, "fetch_caa_artwork", fake_fetch)
    monkeypatch.setattr(artwork_utils, "fetch_spotify_artwork", lambda *_: None)
    monkeypatch.setattr(artwork_utils, "embed_artwork", lambda *_: None)
    monkeypatch.setattr(artwork_utils, "extract_embed_info", lambda *_: None)

    worker = ArtworkWorker(
        storage_directory=tmp_path / "artwork",
        config=_make_artwork_config(tmp_path / "artwork", fallback_enabled=False),
    )
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            metadata={"artist": "Artist", "album": "Album"},
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    assert calls == []

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is False
        assert refreshed.artwork_status == "failed"


@pytest.mark.asyncio
async def test_musicbrainz_fallback_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "fallback.mp3"
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

    fallback_url = "https://coverartarchive.org/release-group/1234/front"
    stored: Dict[str, Any] = {}

    monkeypatch.setattr(artwork_utils, "fetch_spotify_artwork", lambda *_: None)
    monkeypatch.setattr(
        artwork_utils, "fetch_caa_artwork", lambda *_, **__: fallback_url
    )

    def fake_download(url: str, target: Path, **_: Any) -> Path:
        stored["download_url"] = url
        destination = target.with_suffix(".png")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"image-bytes")
        return destination

    def fake_embed(audio_file: Path, artwork_file: Path) -> None:
        stored["embedded"] = (Path(audio_file), Path(artwork_file))

    monkeypatch.setattr(artwork_utils, "download_artwork", fake_download)
    monkeypatch.setattr(artwork_utils, "embed_artwork", fake_embed)

    worker = ArtworkWorker(
        storage_directory=tmp_path / "artwork",
        config=_make_artwork_config(tmp_path / "artwork", fallback_enabled=True),
    )
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            metadata={"artist": "Artist", "album": "Album"},
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    assert stored["download_url"] == fallback_url
    audio_file, art_file = stored["embedded"]
    assert audio_file == audio_path
    assert art_file.name.startswith("1234")

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is True
        assert refreshed.artwork_status == "done"
        assert refreshed.artwork_url == fallback_url
        assert Path(refreshed.artwork_path or "").exists()


@pytest.mark.asyncio
async def test_musicbrainz_fallback_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "fallback-fail.mp3"
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

    fallback_url = "https://coverartarchive.org/release-group/5678/front"

    monkeypatch.setattr(artwork_utils, "fetch_spotify_artwork", lambda *_: None)
    monkeypatch.setattr(
        artwork_utils, "fetch_caa_artwork", lambda *_, **__: fallback_url
    )
    monkeypatch.setattr(artwork_utils, "embed_artwork", lambda *_: None)
    monkeypatch.setattr(artwork_utils, "extract_embed_info", lambda *_: None)

    def raise_download(*_args: Any, **_kwargs: Any) -> Path:
        raise RuntimeError("CAA failure")

    monkeypatch.setattr(artwork_utils, "download_artwork", raise_download)

    worker = ArtworkWorker(
        storage_directory=tmp_path / "artwork",
        config=_make_artwork_config(tmp_path / "artwork", fallback_enabled=True),
    )
    await worker.start()
    try:
        await worker.enqueue(
            download_id,
            str(audio_path),
            metadata={"artist": "Artist", "album": "Album"},
        )
        await worker.wait_for_pending()
    finally:
        await worker.stop()

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.has_artwork is False
        assert refreshed.artwork_status == "failed"
