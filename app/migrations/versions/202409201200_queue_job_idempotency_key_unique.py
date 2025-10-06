"""Ensure queue job idempotency keys are globally unique."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

# revision identifiers, used by Alembic.
revision = "202409201200"
down_revision = "202409091200"
branch_labels = None
depends_on = None


_TABLE_NAME = "queue_jobs"
_UNIQUE_INDEX = "ix_queue_jobs_idempotency_key_not_null"
_LEGACY_INDEX = "ix_queue_jobs_idempotency_key"
_LEGACY_PARTIAL_INDEX = "ix_queue_jobs_type_idempotency_key_not_null"
_LEGACY_CONSTRAINT = "uq_queue_jobs_type_idempotency_key"


def _has_table(connection: Connection) -> bool:
    return connection.dialect.has_table(connection, _TABLE_NAME)


def _get_unique_constraints(connection: Connection) -> set[str]:
    inspector = sa.inspect(connection)
    return {constraint["name"] for constraint in inspector.get_unique_constraints(_TABLE_NAME)}


def _get_indexes(connection: Connection) -> set[str]:
    inspector = sa.inspect(connection)
    return {index["name"] for index in inspector.get_indexes(_TABLE_NAME)}


def upgrade() -> None:
    connection = op.get_bind()
    if not _has_table(connection):
        return

    existing_constraints = _get_unique_constraints(connection)
    if _LEGACY_CONSTRAINT in existing_constraints:
        op.drop_constraint(_LEGACY_CONSTRAINT, _TABLE_NAME, type_="unique")

    existing_indexes = _get_indexes(connection)
    if _LEGACY_PARTIAL_INDEX in existing_indexes:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {_LEGACY_PARTIAL_INDEX}"))
    if _LEGACY_INDEX in existing_indexes:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {_LEGACY_INDEX}"))

    existing_indexes = _get_indexes(connection)
    if _UNIQUE_INDEX not in existing_indexes:
        op.execute(
            sa.text(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {_UNIQUE_INDEX}
                ON {_TABLE_NAME} (idempotency_key)
                WHERE idempotency_key IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    if not _has_table(connection):
        return

    existing_indexes = _get_indexes(connection)
    if _UNIQUE_INDEX in existing_indexes:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {_UNIQUE_INDEX}"))

    existing_indexes = _get_indexes(connection)
    if _LEGACY_INDEX not in existing_indexes:
        op.create_index(_LEGACY_INDEX, _TABLE_NAME, ["idempotency_key"])
    if _LEGACY_PARTIAL_INDEX not in existing_indexes:
        op.execute(
            sa.text(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {_LEGACY_PARTIAL_INDEX}
                ON {_TABLE_NAME} ("type", idempotency_key)
                WHERE idempotency_key IS NOT NULL
                """
            )
        )

    if connection.dialect.name != "sqlite":
        existing_constraints = _get_unique_constraints(connection)
        if _LEGACY_CONSTRAINT not in existing_constraints:
            op.create_unique_constraint(
                _LEGACY_CONSTRAINT,
                _TABLE_NAME,
                ["type", "idempotency_key"],
            )
