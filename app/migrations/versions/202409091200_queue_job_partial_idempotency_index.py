"""Create partial unique index for queue job idempotency."""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "202409091200"
down_revision = "202409041200"
branch_labels = None
depends_on = None


_TABLE_NAME = "queue_jobs"
_CONSTRAINT_NAME = "uq_queue_jobs_type_idempotency_key"
_INDEX_NAME = "ix_queue_jobs_type_idempotency_key_not_null"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _TABLE_NAME, type_="unique")
    op.create_index(
        _INDEX_NAME,
        _TABLE_NAME,
        ["type", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
    op.create_unique_constraint(
        _CONSTRAINT_NAME,
        _TABLE_NAME,
        ["type", "idempotency_key"],
    )
