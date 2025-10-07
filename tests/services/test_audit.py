from datetime import datetime

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import ArtistAuditRecord
from app.services.audit import write_audit


def test_audit_writes_before_after_minimal() -> None:
    reset_engine_for_tests()
    init_db()

    occurred = datetime(2024, 5, 1, 12, 30, 0)
    before = {"title": "Old", "release_date": datetime(2023, 12, 1, 8, 0, 0)}
    after = {"title": "New", "extra": {"tracks": 10}}

    row = write_audit(
        event="updated",
        entity_type="release",
        artist_key="spotify:artist-1",
        entity_id=42,
        job_id="123",
        before=before,
        after=after,
        occurred_at=occurred,
    )

    assert row.artist_key == "spotify:artist-1"
    assert row.event == "updated"
    assert row.before is not None
    assert row.before["release_date"] == "2023-12-01T08:00:00"
    assert row.after is not None
    assert row.after["extra"]["tracks"] == 10

    with session_scope() as session:
        record = session.query(ArtistAuditRecord).one()
        assert record.job_id == "123"
        assert record.before_json["title"] == "Old"
        assert record.after_json["title"] == "New"
