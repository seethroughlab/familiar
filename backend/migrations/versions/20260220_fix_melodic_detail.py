"""Reset melodic flags for tracks missing melodic key in analysis_detail.

293 tracks have has_melodic=true but no "melodic" key in their analysis_detail
JSONB due to a race between run_backfill and run_track_melodic. Resetting the
flags makes them eligible for re-analysis, which will properly merge melodic
data into the existing analysis_detail.

Revision ID: 20260220_fix_melodic
Revises: 20260220_consolidate_av
Create Date: 2026-02-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260220_fix_melodic"
down_revision = "20260220_consolidate_av"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        UPDATE track_analysis
        SET has_melodic = false, melodic_version = 0
        WHERE has_melodic = true
          AND (analysis_detail IS NULL OR analysis_detail->>'melodic' IS NULL)
    """))


def downgrade() -> None:
    # One-way: data backfill
    pass
