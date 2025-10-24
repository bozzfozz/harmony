"""Tests for lightweight SQLite schema migration helpers."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect
from sqlalchemy.engine import Engine

from app.db_migrations import apply_schema_migrations


def _build_seeded_engine(database_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{database_path}")

    metadata = MetaData()
    Table(
        "playlists",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(length=255), nullable=False),
    )
    Table(
        "backfill_jobs",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("status", String(length=32), nullable=False),
    )
    Table(
        "unrelated",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("label", String(length=64), nullable=False),
    )
    metadata.create_all(engine)

    return engine


def test_apply_schema_migrations_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "migrations.db"
    engine = _build_seeded_engine(database_path)

    inspector = inspect(engine)
    unrelated_columns_before = [column["name"] for column in inspector.get_columns("unrelated")]

    apply_schema_migrations(engine)

    inspector_after_first_run = inspect(engine)
    playlist_columns = {column["name"] for column in inspector_after_first_run.get_columns("playlists")}
    backfill_columns = {column["name"] for column in inspector_after_first_run.get_columns("backfill_jobs")}

    assert playlist_columns == {"id", "name", "metadata"}
    assert backfill_columns == {"id", "status", "include_cached_results"}

    # Re-running the migrations should not raise or modify unrelated tables.
    apply_schema_migrations(engine)

    inspector_after_second_run = inspect(engine)
    playlist_columns_second_run = {
        column["name"] for column in inspector_after_second_run.get_columns("playlists")
    }
    backfill_columns_second_run = {
        column["name"] for column in inspector_after_second_run.get_columns("backfill_jobs")
    }
    unrelated_columns_after = [
        column["name"] for column in inspector_after_second_run.get_columns("unrelated")
    ]

    assert playlist_columns_second_run == playlist_columns
    assert backfill_columns_second_run == backfill_columns
    assert unrelated_columns_after == unrelated_columns_before

    engine.dispose()


def test_apply_schema_migrations_handles_missing_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "missing_tables.db"
    engine = create_engine(f"sqlite:///{database_path}")

    metadata = MetaData()
    Table(
        "unrelated",
        metadata,
        Column("id", Integer, primary_key=True),
    )
    metadata.create_all(engine)

    apply_schema_migrations(engine)

    inspector = inspect(engine)
    unrelated_columns = [column["name"] for column in inspector.get_columns("unrelated")]

    assert unrelated_columns == ["id"]

    engine.dispose()
