import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.main import app
from app.models import Download
from app.utils import metadata_utils
from app.workers.metadata_worker import MetadataUpdateWorker, MetadataWorker
from tests.simple_client import SimpleTestClient


class StubMetadataWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[int, Path, Dict[str, Any], Dict[str, Any]]] = []
        self.stopped = False

    async def enqueue(
        self,
        download_id: int,
        audio_path: Path,
        *,
        payload: Dict[str, Any] | None = None,
        request_payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        self.calls.append(
            (
                download_id,
                Path(audio_path),
                dict(payload or {}),
                dict(request_payload or {}),
            )
        )
        return {}

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_metadata_worker_enriches_download(monkeypatch, tmp_path) -> None:
    reset_engine_for_tests()
    init_db()

    audio_file = Path(tmp_path) / "track.flac"
    audio_file.write_bytes(b"data")

    with session_scope() as session:
        download = Download(
            filename=str(audio_file),
            state="completed",
            progress=100.0,
            request_payload={"spotify_id": "track-1"},
        )
        session.add(download)
        session.flush()
        download_id = download.id

    recorded_writes: list[tuple[Path, Dict[str, Any]]] = []

    def fake_write_metadata(path: Path, metadata: Dict[str, Any]) -> None:
        recorded_writes.append((Path(path), dict(metadata)))

    def fake_extract_metadata(track_id: str) -> Dict[str, str]:
        assert track_id == "track-1"
        return {
            "genre": "House",
            "composer": "Composer A",
            "isrc": "ISRC123",
            "artwork_url": "https://cdn.example.com/highres.jpg",
            "copyright": "2024 Example Records",
        }

    monkeypatch.setattr(metadata_utils, "write_metadata_tags", fake_write_metadata)
    monkeypatch.setattr(metadata_utils, "extract_metadata_from_spotify", fake_extract_metadata)

    worker = MetadataWorker()

    metadata = await worker.enqueue(
        download_id,
        audio_file,
        payload={"state": "completed"},
        request_payload={"spotify_id": "track-1"},
    )

    assert metadata["genre"] == "House"
    assert metadata["composer"] == "Composer A"
    assert metadata["isrc"] == "ISRC123"
    assert metadata["copyright"] == "2024 Example Records"

    assert recorded_writes
    path_record, metadata_record = recorded_writes[0]
    assert path_record == audio_file
    assert metadata_record["genre"] == "House"
    assert metadata_record["composer"] == "Composer A"
    assert metadata_record["isrc"] == "ISRC123"
    assert metadata_record["copyright"] == "2024 Example Records"

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.genre == "House"
        assert refreshed.composer == "Composer A"
        assert refreshed.isrc == "ISRC123"
        assert refreshed.copyright == "2024 Example Records"


def test_extract_metadata_from_spotify(monkeypatch) -> None:
    class StubSpotifyClient:
        def get_track_details(self, track_id: str) -> Dict[str, Any]:
            assert track_id == "track-123"
            return {
                "genres": ["House"],
                "credits": {"producer": "Producer X"},
                "external_ids": {"isrc": "ISRC999"},
                "album": {
                    "genres": ["Dance"],
                    "copyrights": [{"text": "2024 Example Records"}],
                    "images": [
                        {
                            "url": "https://example.com/art.jpg",
                            "width": 640,
                            "height": 640,
                        }
                    ],
                },
            }

        def get_track_metadata(self, track_id: str) -> Dict[str, Any]:
            assert track_id == "track-123"
            return {"producer": "Producer Supplemental"}

    stub_client = StubSpotifyClient()
    monkeypatch.setattr(metadata_utils, "SPOTIFY_CLIENT", stub_client)

    metadata = metadata_utils.extract_metadata_from_spotify("track-123")

    assert metadata["genre"] == "House"
    assert metadata["producer"] == "Producer X"
    assert metadata["isrc"] == "ISRC999"
    assert metadata["copyright"] == "2024 Example Records"
    assert metadata["artwork_url"] == "https://example.com/art.jpg"

    monkeypatch.setattr(metadata_utils, "SPOTIFY_CLIENT", None)


def test_write_metadata_tags(monkeypatch, tmp_path) -> None:
    audio_file = tmp_path / "track.mp3"
    audio_file.write_bytes(b"data")

    stored: Dict[str, Any] = {}

    class FakeAudio:
        def __init__(self) -> None:
            self.tags: Dict[str, Any] = {}

        def __setitem__(self, key: str, value: Any) -> None:
            self.tags[key] = value

        def save(self) -> None:
            stored.update(self.tags)

    fake_audio = FakeAudio()

    def fake_file(path: Path, easy: bool = True) -> FakeAudio:
        assert path == audio_file
        return fake_audio

    monkeypatch.setattr(metadata_utils, "mutagen", SimpleNamespace(File=fake_file))

    metadata_utils.write_metadata_tags(
        audio_file,
        {
            "genre": "House",
            "composer": "Composer X",
            "producer": "Producer Y",
            "isrc": "ISRC123",
            "copyright": "2024 Example Records",
        },
    )

    assert stored["genre"] == ["House"]
    assert stored["composer"] == ["Composer X"]
    assert stored["producer"] == ["Producer Y"]
    assert stored["isrc"] == ["ISRC123"]
    assert stored["copyright"] == ["2024 Example Records"]


def test_download_metadata_route(monkeypatch) -> None:
    reset_engine_for_tests()
    init_db()

    with session_scope() as session:
        download = Download(
            filename="song.flac",
            state="completed",
            progress=100.0,
            genre="House",
            composer="Composer A",
            producer="Producer B",
            isrc="ISRC123",
            copyright="2024 Example Records",
        )
        session.add(download)
        session.flush()
        download_id = download.id

    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")

    with SimpleTestClient(app) as client:
        response = client.get(f"/soulseek/download/{download_id}/metadata")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == download_id
    assert payload["genre"] == "House"
    assert payload["composer"] == "Composer A"
    assert payload["producer"] == "Producer B"
    assert payload["isrc"] == "ISRC123"
    assert payload["copyright"] == "2024 Example Records"


def test_refresh_metadata_route(monkeypatch, tmp_path) -> None:
    reset_engine_for_tests()
    init_db()

    audio_file = Path(tmp_path) / "refresh.flac"
    audio_file.write_bytes(b"data")

    with session_scope() as session:
        download = Download(
            filename=str(audio_file),
            state="completed",
            progress=100.0,
            request_payload={"spotify_id": "track-1"},
        )
        session.add(download)
        session.flush()
        download_id = download.id

    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")

    worker = StubMetadataWorker()

    with SimpleTestClient(app) as client:
        client.app.state.rich_metadata_worker = worker

        response = client.post(f"/soulseek/download/{download_id}/metadata/refresh")

        assert response.status_code == 202
        assert response.json() == {"status": "queued"}

        client._loop.run_until_complete(asyncio.sleep(0))

    assert worker.calls
    job_download_id, job_path, job_payload, job_request_payload = worker.calls[0]
    assert job_download_id == download_id
    assert job_path == audio_file


@pytest.mark.asyncio
async def test_metadata_update_worker_processes_downloads(tmp_path) -> None:
    reset_engine_for_tests()
    init_db()

    audio_one = tmp_path / "one.flac"
    audio_two = tmp_path / "two.flac"
    audio_one.write_bytes(b"data")
    audio_two.write_bytes(b"data")

    with session_scope() as session:
        first = Download(
            filename=str(audio_one),
            state="completed",
            progress=100.0,
            genre="Rock",
        )
        second = Download(
            filename=str(audio_two),
            state="completed",
            progress=100.0,
            composer="Composer",
        )
        session.add_all([first, second])
        session.flush()
        first_id = first.id
        second_id = second.id

    class RecordingWorker:
        def __init__(self) -> None:
            self.calls: list[tuple[int, Path]] = []

        async def enqueue(
            self,
            download_id: int,
            audio_path: Path,
            *,
            payload: Dict[str, Any] | None = None,
            request_payload: Dict[str, Any] | None = None,
        ) -> Dict[str, Any]:
            self.calls.append((download_id, Path(audio_path)))
            return {"genre": payload.get("genre") if payload else None}

    stub_worker = RecordingWorker()
    update_worker = MetadataUpdateWorker(metadata_worker=stub_worker)

    status = await update_worker.start()
    assert status["status"] == "running"
    assert status["total"] == 2

    for _ in range(10):
        await asyncio.sleep(0)
        status = await update_worker.status()
        if status["status"] == "completed":
            break

    assert status["status"] == "completed"
    assert status["processed"] == 2
    assert status["last_completed_id"] in {first_id, second_id}
    assert stub_worker.calls == [(first_id, audio_one), (second_id, audio_two)]


@pytest.mark.asyncio
async def test_metadata_update_worker_stop(tmp_path) -> None:
    reset_engine_for_tests()
    init_db()

    paths = []
    for index in range(3):
        file_path = tmp_path / f"slow-{index}.flac"
        file_path.write_bytes(b"data")
        paths.append(file_path)

    with session_scope() as session:
        for file_path in paths:
            session.add(
                Download(
                    filename=str(file_path),
                    state="completed",
                    progress=100.0,
                )
            )

    class SlowWorker:
        def __init__(self) -> None:
            self.calls = 0

        async def enqueue(self, download_id: int, audio_path: Path, **_: Any) -> Dict[str, Any]:
            self.calls += 1
            await asyncio.sleep(0)
            return {}

    stub_worker = SlowWorker()
    update_worker = MetadataUpdateWorker(metadata_worker=stub_worker)

    await update_worker.start()
    await asyncio.sleep(0)
    status = await update_worker.stop()

    assert status["status"] in {"stopped", "completed"}
    assert status["processed"] >= 1
    assert stub_worker.calls >= 1


def test_metadata_update_router_flow(monkeypatch, tmp_path) -> None:
    reset_engine_for_tests()
    init_db()

    first = tmp_path / "router-one.flac"
    second = tmp_path / "router-two.flac"
    first.write_bytes(b"data")
    second.write_bytes(b"data")

    with session_scope() as session:
        session.add_all(
            [
                Download(
                    filename=str(first),
                    state="completed",
                    progress=100.0,
                ),
                Download(
                    filename=str(second),
                    state="completed",
                    progress=100.0,
                ),
            ]
        )

    monkeypatch.setenv("HARMONY_DISABLE_WORKERS", "1")

    class RouterWorker:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def enqueue(self, download_id: int, audio_path: Path, **_: Any) -> Dict[str, Any]:
            self.calls.append(download_id)
            await asyncio.sleep(0)
            return {}

    stub_worker = RouterWorker()
    update_worker = MetadataUpdateWorker(metadata_worker=stub_worker)

    with SimpleTestClient(app) as client:
        client.app.state.rich_metadata_worker = stub_worker
        client.app.state.metadata_update_worker = update_worker

        start_response = client.post("/metadata/update")
        assert start_response.status_code == 202
        payload = start_response.json()
        assert payload["status"] == "running"
        assert payload["total"] == 2

        for _ in range(10):
            client._loop.run_until_complete(asyncio.sleep(0))
            status_payload = client.get("/metadata/status").json()
            if status_payload["status"] == "completed":
                break
        else:
            status_payload = client.get("/metadata/status").json()

        assert status_payload["status"] == "completed"
        assert status_payload["processed"] == 2

        stop_payload = client.post("/metadata/stop").json()
        assert stop_payload["status"] == "completed"

    assert len(stub_worker.calls) == 2
