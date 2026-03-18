"""Drop preview_url and preview_source from external_tracks.

Spotify removed preview URLs for new/dev apps (Feb 2026).
These columns are no longer populated.

Revision ID: drop_ext_preview_cols
Revises: add_full_file_hash
Create Date: 2026-02-11
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

revision = "20260211_drop_ext_preview"
down_revision = "20260209_full_file_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if column_exists("external_tracks", "preview_url"):
        op.drop_column("external_tracks", "preview_url")
    if column_exists("external_tracks", "preview_source"):
        op.drop_column("external_tracks", "preview_source")


def downgrade() -> None:
    if not column_exists("external_tracks", "preview_source"):
        op.add_column(
            "external_tracks",
            sa.Column("preview_source", sa.String(20), nullable=True),
        )
    if not column_exists("external_tracks", "preview_url"):
        op.add_column(
            "external_tracks",
            sa.Column("preview_url", sa.String(500), nullable=True),
        )
