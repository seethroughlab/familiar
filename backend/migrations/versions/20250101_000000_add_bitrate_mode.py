"""Add missing columns to various tables.

This migration adds columns that were added to models but may be missing
from existing databases.

Revision ID: 20250101_000000_add_bitrate_mode
Revises: 20241231_000000_baseline
Create Date: 2025-01-01 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250101_000000_add_bitrate_mode"
down_revision: str | None = "20241231_000000_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table AND column_name = :column
            """
        ),
        {"table": table_name, "column": column_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    """Add missing columns to tables."""
    # tracks.bitrate_mode
    if not _column_exists("tracks", "bitrate_mode"):
        op.add_column(
            "tracks",
            sa.Column("bitrate_mode", sa.String(10), nullable=True),
        )

    # playlists.is_wishlist
    if not _column_exists("playlists", "is_wishlist"):
        op.add_column(
            "playlists",
            sa.Column("is_wishlist", sa.Boolean(), nullable=True, server_default="false"),
        )

    # playlists.generation_prompt
    if not _column_exists("playlists", "generation_prompt"):
        op.add_column(
            "playlists",
            sa.Column("generation_prompt", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    """Remove added columns."""
    op.drop_column("tracks", "bitrate_mode")
    op.drop_column("playlists", "is_wishlist")
    op.drop_column("playlists", "generation_prompt")
