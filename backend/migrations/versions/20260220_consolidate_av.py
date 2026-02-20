"""Consolidate Track.analysis_version into TrackAnalysis.

Backfills TrackAnalysis stub rows for tracks that were attempted (have
analysis_version > 0) but have no TrackAnalysis row (failures/skips).
Then drops the redundant Track.analysis_version column.

Also applies per-phase versioning (rename version → features_version,
add embedding_version) if the previous migration's Step 7 was skipped.

Revision ID: 20260220_consolidate_av
Revises: 20260220_unify_analysis
Create Date: 2026-02-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260220_consolidate_av"
down_revision = "20260220_unify_analysis"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table_name, "column": column_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # ── Step 0: Apply per-phase versioning if previous migration's Step 7 was skipped ──
    # The unify_analysis migration may have been deployed before Step 7 was added,
    # so the DB has "version" instead of "features_version" and no "embedding_version".
    if _column_exists("track_analysis", "version") and not _column_exists("track_analysis", "features_version"):
        op.alter_column("track_analysis", "version", new_column_name="features_version")

    if not _column_exists("track_analysis", "embedding_version"):
        op.execute(sa.text(
            "ALTER TABLE track_analysis ADD COLUMN embedding_version INTEGER DEFAULT 0 NOT NULL"
        ))
        # Backfill: tracks that have an embedding were analyzed at features_version
        op.execute(sa.text(
            "UPDATE track_analysis SET embedding_version = features_version "
            "WHERE embedding IS NOT NULL"
        ))

    # Replace old UniqueConstraint: (track_id, version) → (track_id)
    op.execute(sa.text(
        "ALTER TABLE track_analysis DROP CONSTRAINT IF EXISTS uq_track_analysis_version"
    ))
    op.execute(sa.text(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_track_analysis_track_id') THEN "
        "ALTER TABLE track_analysis ADD CONSTRAINT uq_track_analysis_track_id UNIQUE (track_id); "
        "END IF; END $$"
    ))

    # ── Step 1: Backfill TrackAnalysis stubs ──
    # For tracks with analysis_version > 0 but no TrackAnalysis row
    # (failures/skips that were only recorded on the Track column).
    if _column_exists("tracks", "analysis_version"):
        op.execute(sa.text("""
            INSERT INTO track_analysis (id, track_id, features_version, embedding_version, has_melodic, melodic_version)
            SELECT gen_random_uuid(), t.id, t.analysis_version, 0, false, 0
            FROM tracks t
            LEFT JOIN track_analysis ta ON ta.track_id = t.id
            WHERE ta.id IS NULL AND t.analysis_version > 0
        """))

        # ── Step 2: Drop the column ──
        op.drop_column("tracks", "analysis_version")


def downgrade() -> None:
    # Re-add analysis_version column
    if not _column_exists("tracks", "analysis_version"):
        op.add_column(
            "tracks",
            sa.Column("analysis_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        )

    # Backfill from TrackAnalysis.features_version
    op.execute(sa.text("""
        UPDATE tracks t
        SET analysis_version = ta.features_version
        FROM track_analysis ta
        WHERE ta.track_id = t.id
    """))
