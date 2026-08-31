"""Drop artist_check_cache.check_priority and priority_updated_at.

Not merely unused, though they are: `check_priority` was 0.0 on all 520 production
rows and read by no code, because `get_prioritized_artists_batch` recomputes the
score in SQL on every run.

**The reason they should not be wired up instead is that the value is
profile-relative and the table is not.** `ArtistCheckCache`'s primary key is
`artist_name_normalized` — one row per artist, for the whole installation — while
the priority is computed against one profile's `ProfilePlayHistory`. Any stored
number is one listener's opinion imposed on everyone else sharing the library,
which is the same defect as the first-profile pick that ADR-0099's Phase 2 replaced
with a round-robin. Recomputing per run is both correct and cheap at this size.

ADR-0101 records the audit that found them.

Revision ID: 20260831_drop_check_prio
Revises: 20260825_track_videos
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

revision: str = "20260831_drop_check_prio"
down_revision: str | None = "20260825_track_videos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if column_exists("artist_check_cache", "check_priority"):
        op.drop_column("artist_check_cache", "check_priority")
    if column_exists("artist_check_cache", "priority_updated_at"):
        op.drop_column("artist_check_cache", "priority_updated_at")


def downgrade() -> None:
    # Restores the columns, not their meaning: they held 0.0 for every row, and
    # nothing has ever written anything else.
    if not column_exists("artist_check_cache", "check_priority"):
        op.add_column(
            "artist_check_cache",
            sa.Column(
                "check_priority",
                sa.Float(),
                nullable=False,
                server_default="0",
            ),
        )
    if not column_exists("artist_check_cache", "priority_updated_at"):
        op.add_column(
            "artist_check_cache",
            sa.Column("priority_updated_at", sa.DateTime(), nullable=True),
        )
