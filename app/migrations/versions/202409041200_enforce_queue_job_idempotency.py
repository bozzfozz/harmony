"""Enforce queue job idempotency uniqueness."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

# revision identifiers, used by Alembic.
revision = "202409041200"
down_revision = "202406141200"
branch_labels = None
depends_on = None


_TABLE_NAME = "queue_jobs"
_CONSTRAINT_NAME = "uq_queue_jobs_type_idempotency_key"


def _has_table(connection: Connection) -> bool:
    return connection.dialect.has_table(connection, _TABLE_NAME)


def _get_unique_constraints(connection: Connection) -> set[str]:
    inspector = sa.inspect(connection)
    return {constraint["name"] for constraint in inspector.get_unique_constraints(_TABLE_NAME)}


def upgrade() -> None:
    connection = op.get_bind()
    if not _has_table(connection):
        return

    dedupe_statement = sa.text(
        """
        DELETE FROM queue_jobs
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY type, idempotency_key
                           ORDER BY id
                       ) AS rn
                FROM queue_jobs
                WHERE idempotency_key IS NOT NULL
            ) AS duplicates
            WHERE duplicates.rn > 1
        )
        """
    )
    op.execute(dedupe_statement)

    if connection.dialect.name == "sqlite":
        # SQLite does not support ALTER TABLE ADD CONSTRAINT operations.
        return

    existing_constraints = _get_unique_constraints(connection)
    if _CONSTRAINT_NAME not in existing_constraints:
        op.create_unique_constraint(
            _CONSTRAINT_NAME,
            _TABLE_NAME,
            ["type", "idempotency_key"],
        )


def downgrade() -> None:
    connection = op.get_bind()
    if not _has_table(connection):
        return

    if connection.dialect.name == "sqlite":
        return

    existing_constraints = _get_unique_constraints(connection)
    if _CONSTRAINT_NAME in existing_constraints:
        op.drop_constraint(_CONSTRAINT_NAME, _TABLE_NAME, type_="unique")
