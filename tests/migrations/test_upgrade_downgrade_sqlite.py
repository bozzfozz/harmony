"""Migration smoke tests against SQLite."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command

from .helpers import assert_queue_jobs_schema, make_config


def test_upgrade_downgrade_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "sqlite.db"
    database_url = f"sqlite:///{database_path}"

    config = make_config(database_url)
    command.upgrade(config, "head")

    engine = sa.create_engine(database_url)
    try:
        assert_queue_jobs_schema(engine)
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = sa.create_engine(database_url)
    try:
        assert_queue_jobs_schema(engine)
    finally:
        engine.dispose()
