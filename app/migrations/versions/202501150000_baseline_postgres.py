"""Baseline schema snapshot for Harmony."""

from __future__ import annotations

from alembic import op

revision = "202501150000"
down_revision = None
branch_labels = None
depends_on = None


def _load_metadata() -> None:
    """Ensure SQLAlchemy metadata is populated before running DDL."""

    from app import models  # noqa: F401  # Import models for side-effects


def upgrade() -> None:
    _load_metadata()

    from app.db import metadata

    bind = op.get_bind()
    metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    _load_metadata()

    from app.db import metadata

    bind = op.get_bind()
    metadata.drop_all(bind=bind, checkfirst=True)
