"""Create partial unique index for queue job idempotency."""

import sqlalchemy as sa
from alembic import op

from app.migrations import helpers

# revision identifiers, used by Alembic.
revision = "202409091200"
down_revision = "202409041200"
branch_labels = None
depends_on = None


_TABLE_NAME = "queue_jobs"
_CONSTRAINT_NAME = "uq_queue_jobs_type_idempotency_key"
_INDEX_NAME = "ix_queue_jobs_type_idempotency_key_not_null"


def upgrade() -> None:
    inspector = helpers.get_inspector()
    if not helpers.has_table(inspector, _TABLE_NAME):
        return

    helpers.drop_unique_constraint_if_exists(
        inspector, _TABLE_NAME, _CONSTRAINT_NAME
    )
    helpers.create_index_if_missing(
        inspector,
        _TABLE_NAME,
        _INDEX_NAME,
        ["type", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    inspector = helpers.get_inspector()
    if not helpers.has_table(inspector, _TABLE_NAME):
        return

    helpers.drop_index_if_exists(inspector, _TABLE_NAME, _INDEX_NAME)
    helpers.create_unique_constraint_if_missing(
        inspector,
        _TABLE_NAME,
        _CONSTRAINT_NAME,
        ["type", "idempotency_key"],
    )
