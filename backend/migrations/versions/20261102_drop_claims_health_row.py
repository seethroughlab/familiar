"""Drop the commons claim phase's health row (ADR-0159 point 3).

`recording_backfill`'s claim phase recorded its health under `community_cache_claims`. The
phase is gone, so the row would otherwise sit in `/health/discovery-sources` forever, reporting
the state it was last left in. Nothing else refers to it. The downgrade does not recreate it:
the row is written by the code that used it, and that code is gone.

Revision ID: 20261102_drop_claims_health_row
Revises: 20261003_artist_images
"""

from collections.abc import Sequence

from alembic import op

from migrations.helpers import table_exists

revision: str = "20261102_drop_claims_health_row"
down_revision: str | None = "20261003_artist_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if table_exists("discovery_source_health"):
        op.execute("DELETE FROM discovery_source_health WHERE source = 'community_cache_claims'")


def downgrade() -> None:
    # One-way: the row is written by the claim phase, and that code is gone (ADR-0159).
    pass
