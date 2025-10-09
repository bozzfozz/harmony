"""Ensure queue job idempotency keys are globally unique."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.migrations import helpers

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
    inspector = helpers.get_inspector()
    if not helpers.has_table(inspector, _TABLE_NAME):
        return

    helpers.drop_unique_constraint_if_exists(
        inspector, _TABLE_NAME, _LEGACY_CONSTRAINT
    )
    helpers.drop_index_if_exists(inspector, _TABLE_NAME, _LEGACY_PARTIAL_INDEX)
    helpers.drop_index_if_exists(inspector, _TABLE_NAME, _LEGACY_INDEX)
    helpers.create_index_if_missing(
        inspector,
        _TABLE_NAME,
        _UNIQUE_INDEX,
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    inspector = helpers.get_inspector()
    if not helpers.has_table(inspector, _TABLE_NAME):
        return

    helpers.drop_index_if_exists(inspector, _TABLE_NAME, _UNIQUE_INDEX)
    helpers.create_index_if_missing(
        inspector,
        _TABLE_NAME,
        _LEGACY_INDEX,
        ["idempotency_key"],
    )
    helpers.create_index_if_missing(
        inspector,
        _TABLE_NAME,
        _LEGACY_PARTIAL_INDEX,
        ["type", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    helpers.create_unique_constraint_if_missing(
        inspector,
        _TABLE_NAME,
        _LEGACY_CONSTRAINT,
        ["type", "idempotency_key"],
    )
