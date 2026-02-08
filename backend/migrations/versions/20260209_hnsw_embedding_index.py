"""Add HNSW index on track_analysis embedding column.

Replaces sequential scans for cosine-distance similarity queries with
approximate nearest-neighbor lookups (~10-40x faster at 23K tracks).

Revision ID: 20260209_hnsw_idx
Revises: 20260208_subsonic_creds
Create Date: 2026-02-09 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260209_hnsw_idx"
down_revision: str | None = "20260208_subsonic_creds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_track_analysis_embedding_hnsw"


def _index_exists(index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :name"
        ),
        {"name": index_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if not _index_exists(INDEX_NAME):
        op.execute(
            f"CREATE INDEX {INDEX_NAME} "
            "ON track_analysis USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    if _index_exists(INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="track_analysis")
