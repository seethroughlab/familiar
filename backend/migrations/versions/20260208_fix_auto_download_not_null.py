"""Fix auto_download columns to be NOT NULL (matching model).

Revision ID: 20260208_autodownload_nn
Revises: 20260206_track_file_size
Create Date: 2026-02-08 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260208_autodownload_nn"
down_revision: str | None = "20260206_track_file_size"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Set auto_download NOT NULL on playlists and smart_playlists."""
    # Backfill any NULLs before adding constraint
    op.execute("UPDATE playlists SET auto_download = false WHERE auto_download IS NULL")
    op.execute("UPDATE smart_playlists SET auto_download = false WHERE auto_download IS NULL")

    op.alter_column(
        "playlists",
        "auto_download",
        existing_type=sa.Boolean(),
        nullable=False,
        existing_server_default=sa.text("false"),
    )
    op.alter_column(
        "smart_playlists",
        "auto_download",
        existing_type=sa.Boolean(),
        nullable=False,
        existing_server_default=sa.text("false"),
    )


def downgrade() -> None:
    """Revert auto_download to nullable."""
    op.alter_column(
        "smart_playlists",
        "auto_download",
        existing_type=sa.Boolean(),
        nullable=True,
        existing_server_default=sa.text("false"),
    )
    op.alter_column(
        "playlists",
        "auto_download",
        existing_type=sa.Boolean(),
        nullable=True,
        existing_server_default=sa.text("false"),
    )
