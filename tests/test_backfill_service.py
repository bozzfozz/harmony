from datetime import datetime
from types import MethodType

from app.db import session_scope
from app.dependencies import get_app_config
from app.models import BackfillJob, IngestItem, IngestItemState, IngestJob
from app.services.backfill_service import BackfillService


def test_list_recent_jobs_returns_latest_first() -> None:
    config = get_app_config()
    service = BackfillService(config.spotify, spotify_client=None)
    with session_scope() as session:
        session.add(
            BackfillJob(
                id="job-old",
                state="completed",
                requested_items=10,
                processed_items=10,
                matched_items=5,
                cache_hits=2,
                cache_misses=1,
                expanded_playlists=0,
                expanded_tracks=0,
                expand_playlists=False,
                duration_ms=1000,
                created_at=datetime(2023, 7, 1, 12, 0, 0),
                updated_at=datetime(2023, 7, 1, 12, 5, 0),
            )
        )
        session.add(
            BackfillJob(
                id="job-new",
                state="running",
                requested_items=40,
                processed_items=20,
                matched_items=15,
                cache_hits=8,
                cache_misses=4,
                expanded_playlists=2,
                expanded_tracks=12,
                expand_playlists=True,
                duration_ms=500,
                created_at=datetime(2023, 7, 2, 9, 30, 0),
                updated_at=datetime(2023, 7, 2, 9, 45, 0),
            )
        )

    history = service.list_recent_jobs(limit=5)
    assert [entry.id for entry in history] == ["job-new", "job-old"]
    assert history[0].created_at > history[1].created_at

    top_only = service.list_recent_jobs(limit=1)
    assert [entry.id for entry in top_only] == ["job-new"]

    clamped = service.list_recent_jobs(limit=0)
    assert [entry.id for entry in clamped] == ["job-new"]


def test_create_job_persists_cache_toggle() -> None:
    config = get_app_config()

    class _AuthenticatedSpotify:
        def is_authenticated(self) -> bool:
            return True

    service = BackfillService(config.spotify, spotify_client=_AuthenticatedSpotify())
    spec = service.create_job(
        max_items=None,
        expand_playlists=False,
        include_cached_results=False,
    )

    assert spec.include_cached_results is False

    with session_scope() as session:
        stored = session.get(BackfillJob, spec.id)
        assert stored is not None
        assert stored.include_cached_results is False


def test_run_job_without_cache_skips_cache_lookup() -> None:
    config = get_app_config()

    class _SpotifyStub:
        def __init__(self) -> None:
            self.find_calls: list[tuple[str, str]] = []

        def is_authenticated(self) -> bool:
            return True

        def find_track_match(
            self,
            *,
            artist: str,
            title: str,
            album: str | None,
            duration_ms: int | None,
        ) -> dict[str, object] | None:
            self.find_calls.append((artist, title))
            return {
                "id": "track-1",
                "album": {"id": "album-1"},
                "duration_ms": duration_ms,
                "external_ids": {"isrc": "ISRC123"},
            }

        def get_track_details(self, track_id: str) -> dict[str, object]:
            return {}

    spotify_client = _SpotifyStub()
    service = BackfillService(config.spotify, spotify_client=spotify_client)

    with session_scope() as session:
        session.add(IngestJob(id="ingest-1"))
        session.add(
            IngestItem(
                job_id="ingest-1",
                source_type="TRACK",
                raw_line="",
                artist="Artist",
                title="Title",
                album="Album",
                duration_sec=180,
                dedupe_hash="hash-1",
                source_fingerprint="fingerprint-1",
                state=IngestItemState.REGISTERED.value,
            )
        )

    job_spec = service.create_job(
        max_items=1,
        expand_playlists=False,
        include_cached_results=False,
    )

    cache_calls: list[str] = []

    def _spy_get_cache_entry(self, key: str) -> tuple[str, str | None] | None:
        cache_calls.append(key)
        return ("cached-track", None)

    service._get_cache_entry = MethodType(_spy_get_cache_entry, service)

    service.run_job(job_spec)

    assert cache_calls == []
    assert spotify_client.find_calls == [("Artist", "Title")]

    with session_scope() as session:
        record = session.get(BackfillJob, job_spec.id)
        assert record is not None
        assert record.cache_hits == 0
        assert record.cache_misses == 1
        assert record.include_cached_results is False
