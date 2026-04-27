"""Add partial unique index for listening-profile external album recommendations.

Listening-profile #2 rows have ``source_playlist_id IS NULL`` and
``discovery_context='listening_profile_recommendation'``. Each release_id
appears at most once in this lane (since there's only one listening profile
per Familiar profile). This index enforces that uniqueness without colliding
with #3 ('artist_new_release') or per-playlist #2 ('playlist_recommendation')
rows.

Revision ID: 20260428_listening_prof
Revises: 20260427_ext_album_pl
Create Date: 2026-04-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260428_listening_prof"
down_revision: str | None = "20260427_ext_album_pl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_eac_listening_profile_unique "
        "ON external_album_cache (release_id) "
        "WHERE discovery_context = 'listening_profile_recommendation'"
    )


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
