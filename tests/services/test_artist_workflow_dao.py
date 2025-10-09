from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import reset_engine_for_tests, session_scope
from app.models import ArtistKnownReleaseRecord, Download, WatchlistArtist
from app.services.artist_delta import ArtistKnownRelease
from app.services.artist_workflow_dao import ArtistWorkflowDAO


@pytest.fixture(autouse=True)
def clean_database() -> None:
    reset_engine_for_tests()


def _create_artist(
    *, last_checked: datetime | None = None, retry_block_until: datetime | None = None
) -> int:
    with session_scope() as session:
        record = WatchlistArtist(
            spotify_artist_id=f"artist-{datetime.utcnow().timestamp()}",
            name="Test Artist",
            last_checked=last_checked,
            retry_block_until=retry_block_until,
        )
        session.add(record)
        session.flush()
        return int(record.id)


def test_mark_success_updates_state_and_known_releases() -> None:
    artist_id = _create_artist(
        retry_block_until=datetime.utcnow() + timedelta(minutes=10)
    )
    dao = ArtistWorkflowDAO()
    checked_at = datetime(2024, 1, 1, 12, 0, 0)
    release = ArtistKnownRelease(
        track_id="track-1", etag="etag-1", fetched_at=checked_at
    )

    dao.mark_success(
        artist_id,
        checked_at=checked_at,
        known_releases=[release],
        content_hash="hash-123",
    )

    with session_scope() as session:
        artist = session.get(WatchlistArtist, artist_id)
        assert artist is not None
        assert artist.last_checked == checked_at
        assert artist.retry_block_until is None
        assert artist.last_hash == "hash-123"
        rows = (
            session.execute(
                select(ArtistKnownReleaseRecord).where(
                    ArtistKnownReleaseRecord.artist_id == artist_id
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        stored = rows[0]
        assert stored.track_id == "track-1"
        assert stored.etag == "etag-1"
        assert stored.fetched_at == checked_at


def test_mark_success_normalizes_blank_hash() -> None:
    artist_id = _create_artist()
    dao = ArtistWorkflowDAO()

    dao.mark_success(
        artist_id,
        checked_at=datetime(2024, 5, 1, 12, 0, 0),
        known_releases=None,
        content_hash="  ",
    )

    with session_scope() as session:
        artist = session.get(WatchlistArtist, artist_id)
        assert artist is not None
        assert artist.last_hash is None


def test_load_batch_respects_cutoff_and_cooldown() -> None:
    now = datetime(2024, 1, 1, 10, 0, 0)
    due_id = _create_artist(last_checked=now - timedelta(days=1))
    _create_artist(
        last_checked=now - timedelta(days=2), retry_block_until=now + timedelta(hours=1)
    )
    _create_artist(last_checked=now + timedelta(hours=2))
    dao = ArtistWorkflowDAO()

    rows = dao.load_batch(5, cutoff=now)
    ids = {row.id for row in rows}
    assert due_id in ids
    assert len(ids) == 1


def test_load_batch_normalizes_persisted_blank_hash() -> None:
    artist_id = _create_artist()
    with session_scope() as session:
        artist = session.get(WatchlistArtist, artist_id)
        assert artist is not None
        artist.last_hash = "\t"
        session.add(artist)

    dao = ArtistWorkflowDAO()
    rows = dao.load_batch(1, cutoff=datetime.utcnow())

    assert rows
    assert rows[0].id == artist_id
    assert rows[0].last_hash is None


def test_create_download_record_persists_known_release_transactionally() -> None:
    artist_id = _create_artist()
    dao = ArtistWorkflowDAO()
    release = ArtistKnownRelease(
        track_id="track-42",
        etag="etag-42",
        fetched_at=datetime(2024, 1, 2, 9, 30, 0),
    )

    download_id = dao.create_download_record(
        username="tester",
        filename="artist-track.flac",
        priority=5,
        spotify_track_id="track-42",
        spotify_album_id="album-1",
        payload={"filename": "artist-track.flac"},
        artist_id=artist_id,
        known_release=release,
    )

    assert download_id is not None
    with session_scope() as session:
        download = session.get(Download, int(download_id))
        assert download is not None
        assert download.spotify_track_id == "track-42"
        stored = (
            session.execute(
                select(ArtistKnownReleaseRecord).where(
                    ArtistKnownReleaseRecord.artist_id == artist_id
                )
            )
            .scalars()
            .one()
        )
        assert stored.track_id == "track-42"
        assert stored.etag == "etag-42"

    class ExplodingDAO(ArtistWorkflowDAO):
        def _upsert_known_release(self, *args, **kwargs) -> None:  # type: ignore[override]
            raise RuntimeError("boom")

    exploding = ExplodingDAO()
    with pytest.raises(RuntimeError):
        exploding.create_download_record(
            username="tester",
            filename="explode.flac",
            priority=0,
            spotify_track_id="track-99",
            spotify_album_id="album-9",
            payload={"filename": "explode.flac"},
            artist_id=artist_id,
            known_release=ArtistKnownRelease(
                track_id="track-99", etag="etag-99", fetched_at=None
            ),
        )

    with session_scope() as session:
        downloads = (
            session.execute(select(Download).where(Download.filename == "explode.flac"))
            .scalars()
            .all()
        )
        assert downloads == []


def test_create_download_record_updates_known_release_versioning() -> None:
    artist_id = _create_artist()
    dao = ArtistWorkflowDAO()
    initial = ArtistKnownRelease(
        track_id="track-ver",
        etag="etag-old",
        fetched_at=datetime(2024, 1, 1, 12, 0, 0),
    )
    dao.create_download_record(
        username="tester",
        filename="first.flac",
        priority=1,
        spotify_track_id="track-ver",
        spotify_album_id="album-1",
        payload={},
        artist_id=artist_id,
        known_release=initial,
    )

    updated = ArtistKnownRelease(
        track_id="track-ver",
        etag="etag-new",
        fetched_at=datetime(2024, 2, 1, 8, 30, 0),
    )
    dao.create_download_record(
        username="tester",
        filename="second.flac",
        priority=1,
        spotify_track_id="track-ver",
        spotify_album_id="album-1",
        payload={},
        artist_id=artist_id,
        known_release=updated,
    )

    with session_scope() as session:
        rows = (
            session.execute(
                select(ArtistKnownReleaseRecord).where(
                    ArtistKnownReleaseRecord.artist_id == artist_id,
                    ArtistKnownReleaseRecord.track_id == "track-ver",
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        stored = rows[0]
        assert stored.etag == "etag-new"
        assert stored.fetched_at == datetime(2024, 2, 1, 8, 30, 0)
