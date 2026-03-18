"""Add auto_download column to playlists and smart_playlists.

Revision ID: 20260206_add_auto_download
Revises: 20250101_000000_add_bitrate_mode
Create Date: 2026-02-06 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = "20260206_add_auto_download"
down_revision: str | None = "20250101_000000_add_bitrate_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add auto_download to playlists and smart_playlists."""
    if not column_exists("playlists", "auto_download"):
        op.add_column(
            "playlists",
            sa.Column("auto_download", sa.Boolean(), nullable=True, server_default="false"),
        )

    if not column_exists("smart_playlists", "auto_download"):
        op.add_column(
            "smart_playlists",
            sa.Column("auto_download", sa.Boolean(), nullable=True, server_default="false"),
        )


def downgrade() -> None:
    """Remove auto_download columns."""
    op.drop_column("smart_playlists", "auto_download")
    op.drop_column("playlists", "auto_download")
