from datetime import datetime

from app.dependencies import get_app_config
from app.db import session_scope
from app.models import BackfillJob
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
