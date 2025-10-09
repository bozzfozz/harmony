from pathlib import Path
import random
from typing import Any, List, Mapping, Optional

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download
from app.orchestrator.handlers import (
    SyncHandlerDeps,
    SyncRetryPolicy,
    fanout_download_completion,
    process_sync_payload,
)
from app.utils.activity import activity_manager
from app.utils.events import DOWNLOAD_RETRY_FAILED, DOWNLOAD_RETRY_SCHEDULED


class StubSoulseekClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: List[Mapping[str, Any]] = []

    async def download(self, payload: Mapping[str, Any]) -> None:
        self.calls.append(dict(payload))
        if self.error is not None:
            raise self.error


class StubMetadataService:
    def __init__(self) -> None:
        self.calls: List[tuple[int, Path]] = []

    async def enqueue(
        self,
        download_id: int,
        file_path: Path,
        *,
        payload: Mapping[str, Any] | None,
        request_payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        self.calls.append((download_id, file_path))
        return {
            "artwork_url": "https://example.com/art.jpg",
            "title": "Example Title",
            "metadata": {"genre": "rock"},
        }


class StubArtworkService:
    def __init__(self) -> None:
        self.calls: List[Mapping[str, Any]] = []

    async def enqueue(
        self,
        download_id: int,
        file_path: str,
        *,
        metadata: Mapping[str, Any],
        spotify_track_id: Optional[str],
        spotify_album_id: Optional[str],
        artwork_url: Optional[str],
    ) -> None:
        self.calls.append(
            {
                "download_id": download_id,
                "file_path": file_path,
                "metadata": dict(metadata),
                "track_id": spotify_track_id,
                "album_id": spotify_album_id,
                "artwork_url": artwork_url,
            }
        )


class StubLyricsService:
    def __init__(self) -> None:
        self.calls: List[Mapping[str, Any]] = []

    async def enqueue(
        self,
        download_id: int,
        file_path: str,
        track_info: Mapping[str, Any],
    ) -> None:
        self.calls.append(
            {
                "download_id": download_id,
                "file_path": file_path,
                "track_info": dict(track_info),
            }
        )


@pytest.mark.asyncio
async def test_process_sync_payload_marks_downloads_downloading(tmp_path: Path) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    client = StubSoulseekClient()
    deps = SyncHandlerDeps(
        soulseek_client=client,
        retry_policy_override=SyncRetryPolicy(max_attempts=3, base_seconds=1.0, jitter_pct=0.0),
        rng=random.Random(0),
        music_dir=tmp_path,
    )

    with session_scope() as session:
        record = Download(
            filename="track.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=5,
        )
        session.add(record)
        session.flush()
        download_id = record.id

    payload = {
        "username": "tester",
        "files": [{"download_id": download_id, "priority": 5, "filename": "track.mp3"}],
        "priority": 5,
    }

    result = await process_sync_payload(payload, deps)

    assert result == {"username": "tester", "download_ids": [download_id]}
    assert client.calls and client.calls[0]["files"][0]["download_id"] == download_id

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "downloading"
        assert refreshed.next_retry_at is None


@pytest.mark.asyncio
async def test_process_sync_payload_handles_failure(tmp_path: Path) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    client = StubSoulseekClient(error=RuntimeError("boom"))
    deps = SyncHandlerDeps(
        soulseek_client=client,
        retry_policy_override=SyncRetryPolicy(max_attempts=5, base_seconds=1.0, jitter_pct=0.0),
        rng=random.Random(0),
        music_dir=tmp_path,
    )

    with session_scope() as session:
        record = Download(
            filename="retry.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=3,
        )
        session.add(record)
        session.flush()
        download_id = record.id

    payload = {
        "username": "tester",
        "files": [{"download_id": download_id, "priority": 3, "filename": "retry.mp3"}],
        "priority": 3,
    }

    with pytest.raises(RuntimeError):
        await process_sync_payload(payload, deps)

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "failed"
        assert refreshed.retry_count == 1
        assert refreshed.next_retry_at is not None

    statuses = [entry["status"] for entry in activity_manager.list()]
    assert DOWNLOAD_RETRY_SCHEDULED in statuses


@pytest.mark.asyncio
async def test_process_sync_payload_dead_letters_on_limit(tmp_path: Path) -> None:
    reset_engine_for_tests()
    init_db()
    activity_manager.clear()

    client = StubSoulseekClient(error=RuntimeError("boom"))
    deps = SyncHandlerDeps(
        soulseek_client=client,
        retry_policy_override=SyncRetryPolicy(max_attempts=1, base_seconds=1.0, jitter_pct=0.0),
        rng=random.Random(0),
        music_dir=tmp_path,
    )

    with session_scope() as session:
        record = Download(
            filename="limited.mp3",
            state="queued",
            progress=0.0,
            username="tester",
            priority=2,
            retry_count=1,
        )
        session.add(record)
        session.flush()
        download_id = record.id

    payload = {
        "username": "tester",
        "files": [{"download_id": download_id, "priority": 2, "filename": "limited.mp3"}],
        "priority": 2,
    }

    with pytest.raises(RuntimeError):
        await process_sync_payload(payload, deps)

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "dead_letter"
        assert refreshed.next_retry_at is None
        assert refreshed.retry_count == 2

    statuses = [entry["status"] for entry in activity_manager.list()]
    assert DOWNLOAD_RETRY_FAILED in statuses


@pytest.mark.asyncio
async def test_fanout_download_completion_invokes_services(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reset_engine_for_tests()
    init_db()

    metadata_service = StubMetadataService()
    artwork_service = StubArtworkService()
    lyrics_service = StubLyricsService()
    organized_path = tmp_path / "organized.mp3"

    def fake_organize_file(download: Download, base_dir: Path) -> Path:
        return organized_path

    monkeypatch.setattr("app.orchestrator.handlers.organize_file", fake_organize_file)

    with session_scope() as session:
        record = Download(
            filename=str(tmp_path / "download.mp3"),
            state="downloading",
            progress=0.0,
            username="tester",
            priority=4,
            request_payload={
                "metadata": {"album": "Album"},
                "spotify_track_id": "track123",
                "ingest_item_id": 99,
            },
        )
        session.add(record)
        session.flush()
        download_id = record.id

    deps = SyncHandlerDeps(
        soulseek_client=StubSoulseekClient(),
        metadata_service=metadata_service,
        artwork_service=artwork_service,
        lyrics_service=lyrics_service,
        music_dir=tmp_path,
        retry_policy_override=SyncRetryPolicy(max_attempts=3, base_seconds=1.0, jitter_pct=0.0),
        rng=random.Random(0),
    )

    payload = {
        "filename": str(tmp_path / "download.mp3"),
        "metadata": {"artist": "Artist"},
        "track": {"album": {"id": "album123"}},
    }

    await fanout_download_completion(download_id, payload, deps)

    assert metadata_service.calls
    assert artwork_service.calls and artwork_service.calls[0]["download_id"] == download_id
    assert lyrics_service.calls and lyrics_service.calls[0]["download_id"] == download_id

    with session_scope() as session:
        refreshed = session.get(Download, download_id)
        assert refreshed is not None
        assert refreshed.state == "completed"
        assert refreshed.organized_path == str(organized_path)
        assert refreshed.artwork_url == "https://example.com/art.jpg"
