"""Collapse file-write change scopes to db_only.

The db_and_id3 and db_id3_files scopes are removed as part of the
zero-touch simplification.  Any existing proposed_changes rows that
reference those scopes are migrated to db_only.

Revision ID: 20260318_rm_write_scp
Revises: 20260318_codec_xcode
Create Date: 2026-03-18
"""

import sqlalchemy as sa
from alembic import op

revision = "20260318_rm_write_scp"
down_revision = "20260318_codec_xcode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Cast scope to text for comparison so this works on fresh DBs where
    # the enum never had the removed values.
    conn.execute(
        sa.text(
            "UPDATE proposed_changes SET scope = 'db_only' "
            "WHERE scope::text IN ('db_and_id3', 'db_id3_files')"
        )
    )


def downgrade() -> None:
    pass  # One-way: removed enum values cannot be re-added, no data to restore
