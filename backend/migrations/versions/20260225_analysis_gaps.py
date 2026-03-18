"""Add feature_confidence, local_features, mood_tags, mood_tags_version to track_analysis.

Supports analysis gap fixes: confidence scores, cross-validation,
and CLAP-based mood/genre tags.

Revision ID: 20260225_analysis_gaps
Revises: 20260224_drop_artnorm
Create Date: 2026-02-25
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

revision = "20260225_analysis_gaps"
down_revision = "20260224_drop_artnorm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not column_exists("track_analysis", "feature_confidence"):
        op.add_column(
            "track_analysis",
            sa.Column("feature_confidence", sa.dialects.postgresql.JSONB, nullable=True),
        )

    if not column_exists("track_analysis", "local_features"):
        op.add_column(
            "track_analysis",
            sa.Column("local_features", sa.dialects.postgresql.JSONB, nullable=True),
        )

    if not column_exists("track_analysis", "mood_tags"):
        op.add_column(
            "track_analysis",
            sa.Column("mood_tags", sa.dialects.postgresql.JSONB, nullable=True),
        )
        # GIN index for JSONB containment queries (@>)
        op.create_index(
            "ix_track_analysis_mood_tags",
            "track_analysis",
            ["mood_tags"],
            postgresql_using="gin",
        )

    if not column_exists("track_analysis", "mood_tags_version"):
        op.add_column(
            "track_analysis",
            sa.Column("mood_tags_version", sa.Integer, server_default="0", nullable=False),
        )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_track_analysis_mood_tags"))

    if column_exists("track_analysis", "mood_tags_version"):
        op.drop_column("track_analysis", "mood_tags_version")
    if column_exists("track_analysis", "mood_tags"):
        op.drop_column("track_analysis", "mood_tags")
    if column_exists("track_analysis", "local_features"):
        op.drop_column("track_analysis", "local_features")
    if column_exists("track_analysis", "feature_confidence"):
        op.drop_column("track_analysis", "feature_confidence")
