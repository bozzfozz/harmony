from datetime import datetime

from app.db import session_scope
from app.models import IngestItem, IngestJob
from app.services.backfill_service import BackfillService


def _create_job(job_id: str) -> None:
    with session_scope() as session:
        session.merge(
            IngestJob(
                id=job_id,
                source="FREE",
                state="pending",
                created_at=datetime.utcnow(),
            )
        )


def test_backfill_service_enriches_tracks(backfill_service: BackfillService) -> None:
    service = backfill_service

    job_id = "job-service-1"
    _create_job(job_id)

    with session_scope() as session:
        item = IngestItem(
            job_id=job_id,
            source_type="FILE",
            playlist_url=None,
            raw_line="Tester - Test Song",
            artist="Tester",
            title="Test Song",
            album="Test Album",
            duration_sec=190,
            dedupe_hash="dedupe-1",
            source_fingerprint="fp-1",
            state="registered",
            created_at=datetime.utcnow(),
        )
        session.add(item)
        session.flush()
        item_id = item.id

    job = service.create_job(max_items=5, expand_playlists=False)
    service.run_job(job)
    status = service.get_status(job.id)
    assert status is not None
    assert status.state == "completed"
    assert status.matched_items == 1

    with session_scope() as session:
        stored = session.get(IngestItem, item_id)
        assert stored is not None
        assert stored.spotify_track_id == "track-1"
        assert stored.spotify_album_id == "album-1"
        assert stored.isrc == "TEST00000001"
        assert stored.duration_sec == 200


def test_backfill_service_expands_playlists(backfill_service: BackfillService) -> None:
    service = backfill_service

    job_id = "job-service-2"
    _create_job(job_id)

    playlist_url = "https://open.spotify.com/playlist/playlist-1"
    with session_scope() as session:
        playlist_item = IngestItem(
            job_id=job_id,
            source_type="LINK",
            playlist_url=playlist_url,
            raw_line=None,
            artist=None,
            title=None,
            album=None,
            duration_sec=None,
            dedupe_hash="playlist-dedupe",
            source_fingerprint="playlist-fp",
            state="registered",
            created_at=datetime.utcnow(),
        )
        session.add(playlist_item)
        session.flush()
        playlist_item_id = playlist_item.id

    job = service.create_job(max_items=1, expand_playlists=True)
    service.run_job(job)
    status = service.get_status(job.id)
    assert status is not None
    assert status.state == "completed"

    with session_scope() as session:
        expanded_items = (
            session.query(IngestItem)
            .filter(IngestItem.source_type == "PRO_PLAYLIST_EXPANSION")
            .all()
        )
        assert len(expanded_items) == 1
        new_item = expanded_items[0]
        assert new_item.spotify_track_id == "track-1"
        assert new_item.job_id == job_id
        assert new_item.artist == "Tester"

        playlist_record = session.get(IngestItem, playlist_item_id)
        assert playlist_record is not None
        assert playlist_record.state == "completed"
