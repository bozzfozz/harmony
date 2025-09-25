from __future__ import annotations

from pathlib import Path
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

    monkeypatch.setattr(metadata_utils, "write_metadata", fake_write_metadata)
    monkeypatch.setattr(metadata_utils, "extract_spotify_metadata", fake_extract_metadata)

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
