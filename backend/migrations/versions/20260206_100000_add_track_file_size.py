"""Add file_size column to tracks table.

Revision ID: 20260206_track_file_size
Revises: 20260206_add_auto_download
Create Date: 2026-02-06 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

# revision identifiers, used by Alembic.
revision: str = "20260206_track_file_size"
down_revision: str | None = "20260206_add_auto_download"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not column_exists("tracks", "file_size"):
        op.add_column("tracks", sa.Column("file_size", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    if column_exists("tracks", "file_size"):
        op.drop_column("tracks", "file_size")
