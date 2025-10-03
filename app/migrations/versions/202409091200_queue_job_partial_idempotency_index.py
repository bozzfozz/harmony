"""Create partial unique index for queue job idempotency."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection

# revision identifiers, used by Alembic.
revision = "202409091200"
down_revision = "202409041200"
branch_labels = None
depends_on = None


_TABLE_NAME = "queue_jobs"
_CONSTRAINT_NAME = "uq_queue_jobs_type_idempotency_key"
_INDEX_NAME = "ix_queue_jobs_type_idempotency_key_not_null"


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
    if _CONSTRAINT_NAME in existing_constraints:
        op.drop_constraint(_CONSTRAINT_NAME, _TABLE_NAME, type_="unique")

    existing_indexes = _get_indexes(connection)
    if _INDEX_NAME not in existing_indexes:
        op.execute(
            sa.text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ix_queue_jobs_type_idempotency_key_not_null
                ON queue_jobs ("type", idempotency_key)
                WHERE idempotency_key IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    if not _has_table(connection):
        return

    existing_indexes = _get_indexes(connection)
    if _INDEX_NAME in existing_indexes:
        op.execute(
            sa.text(
                """
                DROP INDEX IF EXISTS ix_queue_jobs_type_idempotency_key_not_null
                """
            )
        )

    if connection.dialect.name == "sqlite":
        return

    existing_constraints = _get_unique_constraints(connection)
    if _CONSTRAINT_NAME not in existing_constraints:
        op.create_unique_constraint(
            _CONSTRAINT_NAME,
            _TABLE_NAME,
            ["type", "idempotency_key"],
        )
