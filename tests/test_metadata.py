from pathlib import Path
from typing import Any, Dict

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download
from app.workers.sync_worker import SyncWorker
from app.core.beets_client import BeetsClient


class RecordingBeetsClient(BeetsClient):
    def __init__(self) -> None:  # pragma: no cover - instantiate without env
        super().__init__()
        self.metadata_calls: list[tuple[str, Dict[str, Any]]] = []
        self.artwork_calls: list[tuple[str, str]] = []

    def update_metadata(self, file_path: str, tags: Dict[str, Any]) -> None:  # type: ignore[override]
        self.metadata_calls.append((str(file_path), dict(tags)))

    def embed_artwork(self, file_path: str, image_url: str) -> None:  # type: ignore[override]
        self.artwork_calls.append((str(file_path), image_url))


class StubSpotifyClient:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def get_track_metadata(self, track_id: str) -> Dict[str, Any]:
        self.requests.append(track_id)
        return {
            "genre": "House",
            "isrc": "ISRC123",
            "artwork_url": "https://cdn.example.com/highres.jpg",
            "copyright": "2024 Example Records",
        }


class StubPlexClient:
    def __init__(self) -> None:
        self.requests: list[str] = []

    async def get_track_metadata(self, item_id: str) -> Dict[str, Any]:
        self.requests.append(item_id)
        return {"composer": "Composer A", "producer": "Producer B"}


class StubSoulseekClient:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload
        self.metadata_requests: list[str] = []

    async def get_download_status(self) -> Dict[str, Any]:
        return {"downloads": [self.payload]}

    async def get_download_metadata(self, download_id: str) -> Dict[str, Any]:
        self.metadata_requests.append(download_id)
        return {"genre": "Soulseek"}


@pytest.mark.asyncio
async def test_completed_download_enriches_metadata(tmp_path) -> None:
    reset_engine_for_tests()
    init_db()

    file_path = Path(tmp_path) / "track.flac"
    file_path.write_bytes(b"data")

    with session_scope() as session:
        download = Download(
            filename=str(file_path),
            state="downloading",
            progress=50.0,
            request_payload={
                "download_id": 1,
                "spotify_id": "track-1",
                "plex_id": "42",
            },
        )
        session.add(download)
        session.flush()
        download_id = download.id

    soulseek_payload = {
        "download_id": download_id,
        "state": "completed",
        "progress": 100.0,
        "local_path": str(file_path),
    }

    beets = RecordingBeetsClient()
    spotify = StubSpotifyClient()
    plex = StubPlexClient()
    soulseek = StubSoulseekClient(soulseek_payload)

    worker = SyncWorker(
        soulseek,
        concurrency=1,
        spotify_client=spotify,
        plex_client=plex,
        beets_client=beets,
    )

    await worker.refresh_downloads()

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "completed"
        assert refreshed.genre == "House"
        assert refreshed.composer == "Composer A"
        assert refreshed.producer == "Producer B"
        assert refreshed.isrc == "ISRC123"
        assert refreshed.artwork_url == "https://cdn.example.com/highres.jpg"

    assert spotify.requests == ["track-1"]
    assert plex.requests == ["42"]
    assert soulseek.metadata_requests == [str(download_id)]

    assert beets.metadata_calls
    path_record, tags_record = beets.metadata_calls[0]
    assert path_record == str(file_path)
    assert tags_record["genre"] == "House"
    assert tags_record["composer"] == "Composer A"
    assert tags_record["producer"] == "Producer B"
    assert tags_record["isrc"] == "ISRC123"
    assert tags_record["copyright"] == "2024 Example Records"

    assert beets.artwork_calls == [
        (str(file_path), "https://cdn.example.com/highres.jpg")
    ]


def test_beets_client_commands(monkeypatch) -> None:
    client = BeetsClient()
    recorded: list[list[str]] = []

    def fake_run(args: Any) -> Any:
        recorded.append(list(args))
        return type("Result", (), {"stdout": ""})()

    monkeypatch.setattr(client, "_run", fake_run)

    client.update_metadata("/music/track.flac", {"genre": "Electronic", "isrc": "ISRC999"})

    assert recorded[0] == [
        "beet",
        "modify",
        "-y",
        "/music/track.flac",
        "genre=Electronic",
        "isrc=ISRC999",
    ]
    assert recorded[1] == [
        "beet",
        "write",
        "-y",
        "/music/track.flac",
        "-f",
        "genre",
        "-f",
        "isrc",
    ]

    def fake_urlopen(url: str) -> Any:
        class _Response:
            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return b"image-bytes"

        return _Response()

    monkeypatch.setattr("app.core.beets_client.urlopen", fake_urlopen)

    client.embed_artwork("/music/track.flac", "https://example.com/cover.jpg")

    assert len(recorded) == 3
    embed_args = recorded[2]
    assert embed_args[:3] == ["beet", "embedart", "-f"]
    temp_path = Path(embed_args[3])
    assert not temp_path.exists()
    assert embed_args[4] == "/music/track.flac"
