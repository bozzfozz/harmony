"""Enforce queue job idempotency uniqueness."""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "202409041200"
down_revision = "202406141200"
branch_labels = None
depends_on = None


_TABLE_NAME = "queue_jobs"
_CONSTRAINT_NAME = "uq_queue_jobs_type_idempotency_key"


def upgrade() -> None:
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
    op.create_unique_constraint(
        _CONSTRAINT_NAME,
        _TABLE_NAME,
        ["type", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _TABLE_NAME, type_="unique")
