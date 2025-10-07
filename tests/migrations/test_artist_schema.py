from sqlalchemy import inspect

from app.db import init_db, reset_engine_for_tests, session_scope


def test_migration_adds_inactive_columns_and_audit_table() -> None:
    reset_engine_for_tests()
    init_db()

    with session_scope() as session:
        inspector = inspect(session.bind)
        release_columns = {column["name"] for column in inspector.get_columns("artist_releases")}
        assert "inactive_at" in release_columns
        assert "inactive_reason" in release_columns

        audit_columns = {column["name"] for column in inspector.get_columns("artist_audit")}
        expected = {"created_at", "job_id", "artist_key", "entity_type", "event"}
        assert expected.issubset(audit_columns)
