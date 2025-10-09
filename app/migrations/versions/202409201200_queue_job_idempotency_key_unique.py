"""Ensure queue job idempotency keys are globally unique."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

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


def upgrade() -> None:
    op.drop_constraint(_LEGACY_CONSTRAINT, _TABLE_NAME, type_="unique")
    op.drop_index(_LEGACY_PARTIAL_INDEX, table_name=_TABLE_NAME)
    op.drop_index(_LEGACY_INDEX, table_name=_TABLE_NAME)
    op.create_index(
        _UNIQUE_INDEX,
        _TABLE_NAME,
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_UNIQUE_INDEX, table_name=_TABLE_NAME)
    op.create_index(_LEGACY_INDEX, _TABLE_NAME, ["idempotency_key"])
    op.create_index(
        _LEGACY_PARTIAL_INDEX,
        _TABLE_NAME,
        ["type", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_unique_constraint(
        _LEGACY_CONSTRAINT,
        _TABLE_NAME,
        ["type", "idempotency_key"],
    )
