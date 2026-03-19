"""Add pending_review and skipped track statuses, review_info column.

Revision ID: 20260319_pend_review
Revises: 20260318_rm_write_scp
Create Date: 2026-03-19
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists, index_exists

revision = "20260319_pend_review"
down_revision = "20260318_rm_write_scp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new enum values (IF NOT EXISTS works in PG 12+)
    op.execute("ALTER TYPE trackstatus ADD VALUE IF NOT EXISTS 'pending_review'")
    op.execute("ALTER TYPE trackstatus ADD VALUE IF NOT EXISTS 'skipped'")

    # Add review_info JSONB column
    if not column_exists("tracks", "review_info"):
        op.add_column("tracks", sa.Column("review_info", sa.dialects.postgresql.JSONB(), nullable=True))

    # Partial index for efficient pending review queries
    if not index_exists("ix_tracks_pending_review"):
        op.create_index(
            "ix_tracks_pending_review",
            "tracks",
            ["created_at"],
            postgresql_where=sa.text("status = 'pending_review'"),
        )


def downgrade() -> None:
    # PG enum values can't be removed, only drop index + column
    if index_exists("ix_tracks_pending_review"):
        op.drop_index("ix_tracks_pending_review", table_name="tracks")
    if column_exists("tracks", "review_info"):
        op.drop_column("tracks", "review_info")
