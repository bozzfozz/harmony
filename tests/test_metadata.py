import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.main import app
from app.models import Download
from app.utils import metadata_utils
from app.workers.metadata_worker import MetadataWorker
from tests.simple_client import SimpleTestClient


class StubPlexClient:
    def __init__(self) -> None:
        self.requests: list[str] = []

    async def get_track_metadata(self, item_id: str) -> Dict[str, Any]:
        self.requests.append(item_id)
        return {"producer": "Producer B"}


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
            request_payload={
                "spotify_id": "track-1",
                "plex_id": "42",
            },
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

    plex = StubPlexClient()
    worker = MetadataWorker(plex_client=plex)

    metadata = await worker.enqueue(
        download_id,
        audio_file,
        payload={"state": "completed"},
        request_payload={"spotify_id": "track-1", "plex_id": "42"},
    )

    assert metadata["genre"] == "House"
    assert metadata["composer"] == "Composer A"
    assert metadata["producer"] == "Producer B"
    assert metadata["isrc"] == "ISRC123"
    assert metadata["copyright"] == "2024 Example Records"

    assert plex.requests == ["42"]
    assert recorded_writes
    path_record, metadata_record = recorded_writes[0]
    assert path_record == audio_file
    assert metadata_record["genre"] == "House"
    assert metadata_record["composer"] == "Composer A"
    assert metadata_record["producer"] == "Producer B"
    assert metadata_record["isrc"] == "ISRC123"
    assert metadata_record["copyright"] == "2024 Example Records"

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.genre == "House"
        assert refreshed.composer == "Composer A"
        assert refreshed.producer == "Producer B"
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


def test_extract_metadata_from_plex() -> None:
    payload = {
        "MediaContainer": {
            "Metadata": [
                {
                    "composers": [{"tag": "Composer X"}],
                    "producers": "Producer Y",
                    "genre": [{"tag": "House"}],
                    "Guid": [{"id": "isrc://ISRC321"}],
                    "copyright": "2023 Example Records",
                }
            ]
        }
    }

    metadata = metadata_utils.extract_metadata_from_plex(payload)

    assert metadata["composer"] == "Composer X"
    assert metadata["producer"] == "Producer Y"
    assert metadata["genre"] == "House"
    assert metadata["isrc"] == "ISRC321"
    assert metadata["copyright"] == "2023 Example Records"


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
    assert job_request_payload["spotify_id"] == "track-1"
