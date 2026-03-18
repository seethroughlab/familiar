"""Add track_deep_analysis table for deep musical analysis.

Stores rich harmonic, melodic, rhythmic, timbral, and structural
analysis results cached per track and versioned independently.

Revision ID: 20260219_deep_analysis
Revises: 20260213_ext_favorites
Create Date: 2026-02-19
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import table_exists

revision = "20260219_deep_analysis"
down_revision = "20260213_ext_favorites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("track_deep_analysis"):
        op.create_table(
            "track_deep_analysis",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("track_id", sa.Uuid(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("results", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("midi_path", sa.String(500), nullable=True),
            sa.Column("section_errors", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("analysis_duration_seconds", sa.Float(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["track_id"], ["tracks.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "track_id", "version", name="uq_track_deep_analysis_version"
            ),
        )
        op.create_index(
            "ix_track_deep_analysis_track_id",
            "track_deep_analysis",
            ["track_id"],
        )


def downgrade() -> None:
    if table_exists("track_deep_analysis"):
        op.drop_table("track_deep_analysis")
