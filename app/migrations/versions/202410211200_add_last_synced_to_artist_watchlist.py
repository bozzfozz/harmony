"""Add last_synced_at to artist_watchlist entries.

Revision ID: 202410211200
Revises: 202410011200
Create Date: 2024-10-21 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "202410211200"
down_revision = "202410011200"
branch_labels = None
depends_on = None

_TABLE = "artist_watchlist"
_COLUMN = "last_synced_at"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if _COLUMN in existing_columns:
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.add_column(sa.Column(_COLUMN, sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if _COLUMN not in existing_columns:
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column(_COLUMN)
