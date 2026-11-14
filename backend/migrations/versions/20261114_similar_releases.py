"""New releases by similar artists, and why each profile gets one (ADR-0180).

A partial unique index gives the new `similar_artist_new_release` context the same
once-per-release identity every other context has, and `profile_release_reasons` records which
played artist brought each release to each profile.

Revision ID: 20261114_similar_releases
Revises: 20261114_profile_discovery_state
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import table_exists

revision: str = "20261114_similar_releases"
down_revision: str | None = "20261114_profile_discovery_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_eac_similar_release_unique "
        "ON external_album_cache (release_id) "
        "WHERE discovery_context = 'similar_artist_new_release'"
    )
    if not table_exists("profile_release_reasons"):
        op.create_table(
            "profile_release_reasons",
            sa.Column(
                "external_album_id",
                sa.UUID(),
                sa.ForeignKey("external_album_cache.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "profile_id",
                sa.UUID(),
                sa.ForeignKey("profiles.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "seed_artist_id",
                sa.UUID(),
                sa.ForeignKey("artists.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("seed_artist_name", sa.String(500), nullable=False),
            sa.Column("match_score", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    if table_exists("profile_release_reasons"):
        op.drop_table("profile_release_reasons")
    op.execute("DROP INDEX IF EXISTS ix_eac_similar_release_unique")
