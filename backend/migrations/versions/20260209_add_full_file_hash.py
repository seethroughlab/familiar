"""Add full_file_hash column to tracks for hash collision detection.

When two files have identical first/last 8KB + size (partial hash collision),
a full SHA-256 hash disambiguates them during relocation detection.

Revision ID: 20260209_full_file_hash
Revises: 20260209_hnsw_idx
Create Date: 2026-02-09 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260209_full_file_hash"
down_revision: str | None = "20260209_hnsw_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table_name, "column": column_name})
    return result.fetchone() is not None


def upgrade() -> None:
    if not _column_exists("tracks", "full_file_hash"):
        op.add_column("tracks", sa.Column("full_file_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    if _column_exists("tracks", "full_file_hash"):
        op.drop_column("tracks", "full_file_hash")
