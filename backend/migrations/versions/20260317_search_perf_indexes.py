"""Add trigram GIN indexes on tracks (title/artist/album) and B-tree indexes
on track_analysis.features_version and frontend_logs.client_ts.

Trigram indexes accelerate LIKE '%substring%' patterns that B-tree can't serve.

Revision ID: 20260317_search_perf_idx
Revises: 20260317_tempo_cv_lang
Create Date: 2026-03-17
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import index_exists

revision = "20260317_search_perf_idx"
down_revision = "20260317_tempo_cv_lang"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pg_trgm extension is available
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    # Trigram GIN indexes for ILIKE/LIKE '%substring%' on tracks
    for col in ("title", "artist", "album"):
        idx_name = f"ix_tracks_{col}_trgm"
        if not index_exists(idx_name):
            op.execute(sa.text(
                f"CREATE INDEX {idx_name} ON tracks USING gin ({col} gin_trgm_ops)"
            ))

    # B-tree index on track_analysis.features_version
    if not index_exists("ix_track_analysis_features_version"):
        op.create_index(
            "ix_track_analysis_features_version",
            "track_analysis",
            ["features_version"],
        )

    # B-tree index on frontend_logs.client_ts
    if not index_exists("ix_frontend_logs_client_ts"):
        op.create_index(
            "ix_frontend_logs_client_ts",
            "frontend_logs",
            ["client_ts"],
        )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tracks_title_trgm"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tracks_artist_trgm"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_tracks_album_trgm"))
    op.drop_index("ix_track_analysis_features_version", table_name="track_analysis")
    op.drop_index("ix_frontend_logs_client_ts", table_name="frontend_logs")
