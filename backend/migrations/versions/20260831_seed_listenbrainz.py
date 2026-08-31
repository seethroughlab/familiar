"""Seed the ListenBrainz row in discovery_source_health.

The table's own migration seeds the sources known when it was written. This adds
one, separately, because that migration has already run everywhere — editing it in
place would seed the row on fresh installs and silently skip every existing one,
which is the drift these idempotent inserts exist to avoid.

Revision ID: 20260831_seed_listenbrainz
Revises: 20260831_disc_src_health
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import table_exists

revision: str = "20260831_seed_listenbrainz"
down_revision: str | None = "20260831_disc_src_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if table_exists("discovery_source_health"):
        op.execute(
            sa.text(
                "INSERT INTO discovery_source_health "
                "  (source, consecutive_failures, items_contributed) "
                "VALUES ('listenbrainz', 0, 0) "
                "ON CONFLICT (source) DO NOTHING"
            )
        )


def downgrade() -> None:
    if table_exists("discovery_source_health"):
        op.execute(
            sa.text("DELETE FROM discovery_source_health WHERE source = 'listenbrainz'")
        )
