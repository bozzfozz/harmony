from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import ArtistRecord, ArtistReleaseRecord, ArtistWatchlistEntry
from app.services.artist_dao import (
    ArtistDao,
    ArtistReleaseUpsertDTO,
    ArtistUpsertDTO,
    build_artist_key,
)


def _setup_database() -> None:
    reset_engine_for_tests()
    init_db()


def test_artist_upsert_is_idempotent_and_updates_version() -> None:
    _setup_database()

    first_timestamp = datetime(2024, 1, 1, 12, 0, 0)
    second_timestamp = datetime(2024, 1, 1, 12, 5, 0)

    dto = ArtistUpsertDTO(
        artist_key=build_artist_key("spotify", "artist-1"),
        source="spotify",
        source_id="artist-1",
        name="Example Artist",
        genres=("rock", "indie"),
        images=("https://img/1",),
        popularity=42,
        metadata={"origin": "test"},
    )

    dao = ArtistDao(now_factory=lambda: first_timestamp)
    first = dao.upsert_artist(dto)

    assert first.updated_at == first_timestamp
    assert first.version

    dao = ArtistDao(now_factory=lambda: second_timestamp)
    second = dao.upsert_artist(dto)
    assert second.updated_at == first.updated_at
    assert second.version == first.version

    updated = replace(dto, name="Renamed Artist", genres=("indie", "rock", "pop"))
    dao = ArtistDao(now_factory=lambda: second_timestamp)
    third = dao.upsert_artist(updated)
    assert third.updated_at == second_timestamp
    assert third.version != first.version

    with session_scope() as session:
        record = session.get(ArtistRecord, first.id)
        assert record is not None
        assert record.name == "Renamed Artist"
        assert sorted(record.genres or []) == ["indie", "pop", "rock"]


def test_release_upsert_batch_handles_duplicates() -> None:
    _setup_database()

    now = datetime(2024, 1, 2, 9, 0, 0)
    dao = ArtistDao(now_factory=lambda: now)
    artist = dao.upsert_artist(
        ArtistUpsertDTO(
            artist_key=build_artist_key("spotify", "artist-2"),
            source="spotify",
            source_id="artist-2",
            name="Another Artist",
        )
    )

    release = ArtistReleaseUpsertDTO(
        artist_key=artist.artist_key,
        source="spotify",
        source_id="release-1",
        title="Debut Album",
        release_date="2024-01-01",
        release_type="album",
        total_tracks=10,
    )

    rows = dao.upsert_releases([release, release])
    assert len(rows) == 1

    later = datetime(2024, 1, 5, 10, 0, 0)
    dao = ArtistDao(now_factory=lambda: later)
    updated_rows = dao.upsert_releases(
        [
            replace(
                release,
                title="Debut Album (Deluxe)",
                total_tracks=12,
                release_date="2024-01-02",
            )
        ]
    )
    assert len(updated_rows) == 1
    assert updated_rows[0].updated_at == later

    with session_scope() as session:
        record = (
            session.execute(
                select(ArtistReleaseRecord).where(
                    ArtistReleaseRecord.artist_key == artist.artist_key
                )
            )
            .scalars()
            .one()
        )
        assert record.title == "Debut Album (Deluxe)"
        assert record.total_tracks == 12
        assert str(record.release_date) == "2024-01-02"


def test_watchlist_batch_respects_cooldown_and_priority() -> None:
    _setup_database()

    now = datetime(2024, 3, 1, 8, 0, 0)
    later = now + timedelta(hours=1)

    with session_scope() as session:
        session.add_all(
            [
                ArtistWatchlistEntry(
                    artist_key="spotify:ready",
                    priority=5,
                    last_enqueued_at=None,
                    cooldown_until=None,
                ),
                ArtistWatchlistEntry(
                    artist_key="spotify:cooldown",
                    priority=10,
                    last_enqueued_at=None,
                    cooldown_until=now + timedelta(hours=2),
                ),
                ArtistWatchlistEntry(
                    artist_key="spotify:due",
                    priority=10,
                    last_enqueued_at=None,
                    cooldown_until=now - timedelta(minutes=5),
                ),
            ]
        )

    dao = ArtistDao()
    batch = dao.get_watchlist_batch(5, now=now)
    assert [item.artist_key for item in batch] == ["spotify:due", "spotify:ready"]

    assert dao.mark_enqueued("spotify:due", now, cooldown_until=later)
    with session_scope() as session:
        entry = session.get(ArtistWatchlistEntry, "spotify:due")
        assert entry is not None
        assert entry.last_enqueued_at == now
        assert entry.cooldown_until == later


__all__ = [
    "test_artist_upsert_is_idempotent_and_updates_version",
    "test_release_upsert_batch_handles_duplicates",
    "test_watchlist_batch_respects_cooldown_and_priority",
]
