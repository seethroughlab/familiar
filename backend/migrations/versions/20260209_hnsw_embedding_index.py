"""Add HNSW index on track_analysis embedding column.

Replaces sequential scans for cosine-distance similarity queries with
approximate nearest-neighbor lookups (~10-40x faster at 23K tracks).

Revision ID: 20260209_hnsw_idx
Revises: 20260208_subsonic_creds
Create Date: 2026-02-09 00:00:00
"""

from collections.abc import Sequence

from alembic import op

from migrations.helpers import index_exists

# revision identifiers, used by Alembic.
revision: str = "20260209_hnsw_idx"
down_revision: str | None = "20260208_subsonic_creds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_track_analysis_embedding_hnsw"


def upgrade() -> None:
    if not index_exists(INDEX_NAME):
        op.execute(
            f"CREATE INDEX {INDEX_NAME} "
            "ON track_analysis USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    if index_exists(INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="track_analysis")
