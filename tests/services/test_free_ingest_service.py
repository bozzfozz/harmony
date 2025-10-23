from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
import inspect
from typing import Any, Awaitable, Callable

import pytest

from app.models import Download, IngestItem, IngestItemState, IngestJob, IngestJobState
from app.services.free_ingest_service import FreeIngestService, PlaylistValidationError


@dataclass(slots=True)
class StubIngestConfig:
    batch_size: int
    max_pending_jobs: int


@dataclass(slots=True)
class StubFreeIngestConfig:
    max_playlists: int
    max_tracks: int
    batch_size: int


@dataclass(slots=True)
class StubAppConfig:
    ingest: StubIngestConfig
    free_ingest: StubFreeIngestConfig


class FakeSoulseekClient:
    """Async stub recording search and download requests."""

    def __init__(self) -> None:
        self.search_queries: list[str] = []
        self.download_requests: list[dict[str, Any]] = []
        self._results: dict[str, dict[str, Any]] = {}

    def set_result(self, query: str, payload: dict[str, Any]) -> None:
        self._results[query] = payload

    async def search(self, query: str, format_priority: tuple[str, ...]) -> dict[str, Any]:
        self.search_queries.append(query)
        payload = self._results.get(query)
        if payload is None:
            payload = {
                "results": [
                    {
                        "username": "collector",
                        "files": [
                            {
                                "name": "sample.flac",
                                "size": 512,
                                "bitrate": 320,
                                "format": "flac",
                            }
                        ],
                    }
                ]
            }
        return copy.deepcopy(payload)

    async def download(self, payload: dict[str, Any]) -> None:
        self.download_requests.append(copy.deepcopy(payload))


class FakeScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class FakeDatabase:
    """In-memory store mimicking the ORM interactions used by the service."""

    def __init__(self) -> None:
        self.jobs: dict[str, IngestJob] = {}
        self.items: dict[int, IngestItem] = {}
        self.downloads: dict[int, Download] = {}
        self.other: list[Any] = []
        self.queries: list[Any] = []
        self.next_item_id = 1
        self.next_download_id = 1

    def count_pending_jobs(self) -> int:
        pending_states = {
            IngestJobState.REGISTERED.value,
            IngestJobState.NORMALIZED.value,
            IngestJobState.QUEUED.value,
        }
        return sum(1 for job in self.jobs.values() if job.state in pending_states)


class FakeSession:
    def __init__(self, database: FakeDatabase) -> None:
        self._db = database

    def add(self, obj: Any) -> None:
        if isinstance(obj, IngestJob):
            self._db.jobs[obj.id] = obj
        elif isinstance(obj, IngestItem):
            if not getattr(obj, "id", None):
                obj.id = self._db.next_item_id
                self._db.next_item_id += 1
            self._db.items[obj.id] = obj
        elif isinstance(obj, Download):
            if not getattr(obj, "id", None):
                obj.id = self._db.next_download_id
                self._db.next_download_id += 1
            self._db.downloads[obj.id] = obj
        else:
            self._db.other.append(obj)

    def flush(self) -> None:
        return None

    def get(self, model: Any, key: Any) -> Any:
        if model is IngestJob:
            return self._db.jobs.get(key)
        if model is IngestItem:
            return self._db.items.get(key)
        if model is Download:
            return self._db.downloads.get(key)
        return None

    def execute(self, query: Any) -> FakeScalarResult:
        self._db.queries.append(query)
        return FakeScalarResult(self._db.count_pending_jobs())


class FakeSessionRunner:
    def __init__(self, database: FakeDatabase) -> None:
        self._db = database
        self.calls: list[str] = []

    async def __call__(self, func: Callable[[FakeSession], Any | Awaitable[Any]]) -> Any:
        self.calls.append(getattr(func, "__name__", repr(func)))
        session = FakeSession(self._db)
        result = func(session)
        if inspect.isawaitable(result):
            return await result
        return result


ServiceBuilderReturn = tuple[
    FreeIngestService,
    FakeDatabase,
    FakeSoulseekClient,
    FakeSessionRunner,
]
ServiceBuilder = Callable[..., ServiceBuilderReturn]


@pytest.fixture()
def service_builder() -> ServiceBuilder:
    def _builder(
        *,
        max_playlists: int = 4,
        max_tracks: int = 16,
        free_batch_size: int = 4,
        ingest_batch_size: int = 4,
        max_pending_jobs: int = 8,
    ) -> ServiceBuilderReturn:
        database = FakeDatabase()
        runner = FakeSessionRunner(database)
        soulseek = FakeSoulseekClient()
        config = StubAppConfig(
            ingest=StubIngestConfig(
                batch_size=ingest_batch_size,
                max_pending_jobs=max_pending_jobs,
            ),
            free_ingest=StubFreeIngestConfig(
                max_playlists=max_playlists,
                max_tracks=max_tracks,
                batch_size=free_batch_size,
            ),
        )
        service = FreeIngestService(
            config=config,
            soulseek_client=soulseek,
            sync_worker=None,
            session_runner=runner,
        )
        return service, database, soulseek, runner

    return _builder


@pytest.mark.asyncio
async def test_submit_raises_for_invalid_playlist_links(
    service_builder: ServiceBuilder,
) -> None:
    service, database, soulseek, _ = service_builder()

    with pytest.raises(PlaylistValidationError) as excinfo:
        await service.submit(
            playlist_links=[
                "https://open.spotify.com/album/not-a-playlist",
                "ftp://open.spotify.com/playlist/abc123",
            ]
        )

    error = excinfo.value
    reasons = {item.reason for item in error.invalid_links}
    assert reasons == {"NOT_A_PLAYLIST", "INVALID_SCHEME"}
    assert database.jobs == {}
    assert soulseek.search_queries == []


@pytest.mark.asyncio
async def test_submit_normalizes_tracks_and_queues_downloads(
    service_builder: ServiceBuilder,
) -> None:
    service, database, soulseek, _ = service_builder(
        max_tracks=8,
        free_batch_size=2,
        ingest_batch_size=1,
    )

    tracks = [
        "   ",
        "Artist One - Track One 03:30",
        "Artist One - Track One 03:30",
        "Artist Two - Track Two (Album Two) 04:05",
    ]

    submission = await service.submit(tracks=tracks, batch_hint=2)

    assert submission.ok is True
    assert submission.error is None
    assert submission.accepted.tracks == 2
    assert submission.accepted.playlists == 0
    assert submission.accepted.batches == 1
    assert submission.skipped.tracks == 2
    assert submission.skipped.playlists == 0
    assert submission.skipped.reason == "invalid"

    assert len(database.jobs) == 1
    job = database.jobs[submission.job_id]
    assert job.state == IngestJobState.COMPLETED.value
    assert job.skipped_tracks == 2
    assert job.error == "invalid"

    assert len(database.items) == 2
    for item in database.items.values():
        assert item.state == IngestItemState.QUEUED.value
    albums = {item.album for item in database.items.values()}
    assert "Album Two" in albums
    durations = {item.duration_sec for item in database.items.values()}
    assert 245 in durations  # 4 minutes 5 seconds

    assert len(database.downloads) == 2
    assert len(soulseek.search_queries) >= 2
    assert len(soulseek.download_requests) == 2
    first_payload = soulseek.download_requests[0]
    assert first_payload["username"] == "collector"
    file_payload = first_payload["files"][0]
    assert file_payload["priority"] == 10
    assert file_payload["download_id"] in database.downloads


@pytest.mark.asyncio
async def test_has_capacity_respects_pending_limit(
    service_builder: Callable[
        ..., tuple[FreeIngestService, FakeDatabase, FakeSoulseekClient, FakeSessionRunner]
    ],
) -> None:
    service, database, _, _ = service_builder(max_pending_jobs=2)

    assert await service._has_capacity() is True

    database.jobs["job-1"] = IngestJob(
        id="job-1",
        source="FREE",
        created_at=datetime.utcnow(),
        state=IngestJobState.REGISTERED.value,
        skipped_playlists=0,
        skipped_tracks=0,
        error=None,
    )
    assert await service._has_capacity() is True

    database.jobs["job-2"] = IngestJob(
        id="job-2",
        source="FREE",
        created_at=datetime.utcnow(),
        state=IngestJobState.QUEUED.value,
        skipped_playlists=0,
        skipped_tracks=0,
        error=None,
    )
    assert await service._has_capacity() is False


@pytest.mark.asyncio
async def test_submit_applies_backpressure_when_capacity_exceeded(
    service_builder: Callable[
        ..., tuple[FreeIngestService, FakeDatabase, FakeSoulseekClient, FakeSessionRunner]
    ],
) -> None:
    service, database, soulseek, _ = service_builder(max_pending_jobs=1)

    existing = IngestJob(
        id="existing-job",
        source="FREE",
        created_at=datetime.utcnow(),
        state=IngestJobState.QUEUED.value,
        skipped_playlists=0,
        skipped_tracks=0,
        error=None,
    )
    database.jobs[existing.id] = existing

    submission = await service.submit(tracks=["Artist Zero - Song Zero 01:23"])

    assert submission.ok is True
    assert submission.accepted.tracks == 0
    assert submission.accepted.playlists == 0
    assert submission.skipped.tracks == 1
    assert submission.skipped.reason == "backpressure"
    assert submission.error == "backpressure"

    assert soulseek.search_queries == []
    assert soulseek.download_requests == []

    job = database.jobs[submission.job_id]
    assert job.state == IngestJobState.COMPLETED.value
    assert job.skipped_tracks == 1
    assert job.error == "backpressure"
