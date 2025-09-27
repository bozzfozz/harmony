import pytest

from sqlalchemy import select

from app.core.matching_engine import MusicMatchingEngine
from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import AutoSyncSkippedTrack, Match, WorkerJob
from app.utils.settings_store import read_setting, write_setting
from app.workers.auto_sync_worker import AutoSyncWorker, TrackInfo
from app.workers.matching_worker import MatchingWorker

try:
    from app.workers.scan_worker import ScanWorker
except ModuleNotFoundError:  # pragma: no cover - archived integration
    pytest.skip("Plex scan worker archived in MVP", allow_module_level=True)

from app.workers.sync_worker import SyncWorker


class DummySoulseekClient:
    def __init__(self) -> None:
        self.downloads: list[dict] = []

    async def download(self, payload: dict) -> None:
        self.downloads.append(payload)

    async def get_download_status(self) -> list[dict]:
        return []


@pytest.mark.asyncio
async def test_sync_worker_persists_jobs() -> None:
    reset_engine_for_tests()
    init_db()
    client = DummySoulseekClient()
    worker = SyncWorker(client, concurrency=1)

    await worker.enqueue({"username": "tester", "files": [{"id": 1, "download_id": 1}]})

    assert client.downloads, "Download should be triggered even when worker is stopped"

    with session_scope() as session:
        job = session.execute(select(WorkerJob)).scalar_one()
        assert job.state == "completed"
        assert job.attempts == 1

    assert read_setting("metrics.sync.jobs_completed") == "1"


@pytest.mark.asyncio
async def test_matching_worker_batch_processing() -> None:
    reset_engine_for_tests()
    init_db()
    engine = MusicMatchingEngine()
    worker = MatchingWorker(engine, batch_size=2, confidence_threshold=0.3)

    job_payload = {
        "type": "spotify-to-plex",
        "spotify_track": {
            "id": "track-1",
            "name": "Sample Song",
            "artists": [{"name": "Sample Artist"}],
        },
        "candidates": [
            {"id": "cand-1", "title": "Sample Song", "artist": "Sample Artist"},
            {"id": "cand-2", "title": "Sample Song", "artist": "Sample Artist"},
        ],
    }

    await worker.enqueue(job_payload)

    with session_scope() as session:
        matches = session.execute(select(Match)).scalars().all()
        assert len(matches) == 2

    assert read_setting("metrics.matching.last_discarded") == "0"


class StubPlexClient:
    def __init__(self) -> None:
        self.refresh_calls: list[tuple[str, bool]] = []

    async def get_libraries(self) -> dict:
        return {
            "MediaContainer": {
                "Directory": [
                    {"key": "1", "type": "artist", "title": "Music"},
                ]
            }
        }

    async def refresh_library_section(self, section_id: str, *, full: bool = False) -> None:
        self.refresh_calls.append((section_id, full))

    async def get_library_statistics(self) -> dict:
        return {"artists": 1, "albums": 1, "tracks": 1}


@pytest.mark.asyncio
async def test_scan_worker_uses_incremental_and_dynamic_interval() -> None:
    reset_engine_for_tests()
    init_db()
    write_setting("scan_worker_incremental", "1")
    write_setting("scan_worker_interval_seconds", "1")
    plex = StubPlexClient()
    worker = ScanWorker(plex)

    assert worker._resolve_interval() == 1

    await worker.request_scan("1")

    assert plex.refresh_calls == [("1", False)]
    assert read_setting("metrics.scan.incremental") == "1"


class StubSoulseekSearchClient:
    def __init__(self) -> None:
        self.results: dict[str, dict] = {}
        self.search_calls: list[str] = []
        self.download_calls: list[dict] = []

    async def search(self, query: str) -> dict:
        self.search_calls.append(query)
        return self.results.get(query, {"results": []})

    async def download(self, payload: dict) -> None:
        self.download_calls.append(payload)

    async def get_download_status(self) -> list[dict]:  # pragma: no cover - unused
        return []


class StubSpotifyClient:
    def get_user_playlists(self) -> dict:
        return {"items": []}

    def get_playlist_items(self, playlist_id: str) -> dict:  # pragma: no cover - unused
        return {"items": []}

    def get_saved_tracks(self) -> dict:
        return {"items": []}


class StubPlexLibraryClient:
    async def get_libraries(self) -> dict:
        return {"MediaContainer": {"Directory": []}}

    async def get_library_statistics(self) -> dict:
        return {"artists": 0, "albums": 0, "tracks": 0}


class StubBeetsClient:
    def __init__(self) -> None:
        self.imports: list[str] = []

    def import_file(self, path: str, quiet: bool = True) -> str:
        self.imports.append(path)
        return path


@pytest.mark.asyncio
async def test_autosync_worker_quality_and_skip_behaviour() -> None:
    reset_engine_for_tests()
    init_db()
    write_setting("autosync_min_bitrate", "320")
    write_setting("autosync_preferred_formats", "flac")
    spotify = StubSpotifyClient()
    plex = StubPlexLibraryClient()
    soulseek = StubSoulseekSearchClient()
    beets = StubBeetsClient()
    worker = AutoSyncWorker(
        spotify_client=spotify,
        plex_client=plex,
        soulseek_client=soulseek,
        beets_client=beets,
        skip_threshold=2,
    )

    track_a = TrackInfo(title="Track A", artist="Artist A", spotify_id="a")
    track_b = TrackInfo(title="Track B", artist="Artist B", spotify_id="b")

    soulseek.results = {
        "Artist A Track A": {
            "results": [{"username": "low", "files": [{"filename": "a.mp3", "bitrate": 128}]}]
        },
        "Artist B Track B": {
            "results": [
                {
                    "username": "flac-user",
                    "files": [
                        {
                            "filename": "b.flac",
                            "bitrate": 320,
                            "format": "flac",
                            "size": 1024,
                        }
                    ],
                },
                {
                    "username": "mp3-user",
                    "files": [
                        {
                            "filename": "b.mp3",
                            "bitrate": 320,
                            "format": "mp3",
                            "size": 800,
                        }
                    ],
                },
            ]
        },
    }

    downloaded, skipped, failures = await worker._download_missing_tracks(
        {track_a, track_b}, "test"
    )

    assert track_b in [entry[0] for entry in downloaded]
    assert track_a in skipped
    assert "quality" in failures
    assert beets.imports == ["b.flac"]
    assert soulseek.download_calls[0]["username"] == "flac-user"

    with session_scope() as session:
        record = session.execute(
            select(AutoSyncSkippedTrack).where(AutoSyncSkippedTrack.track_key == "a")
        ).scalar_one()
        assert record.failure_count == 1

    downloaded, skipped, failures = await worker._download_missing_tracks({track_a}, "test")
    assert "quality" in failures

    downloaded, skipped, failures = await worker._download_missing_tracks({track_a}, "test")
    assert track_a in skipped
    assert soulseek.search_calls.count("Artist A Track A") == 2
