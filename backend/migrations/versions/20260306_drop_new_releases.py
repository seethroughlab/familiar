"""Drop new releases tables (artist_new_releases, artist_check_cache).

Revision ID: 20260306_drop_nr
Revises: 20260306_drop_subsonic
Create Date: 2026-03-06
"""

from alembic import op

from migrations.helpers import table_exists

revision = "20260306_drop_nr"
down_revision = "20260306_drop_subsonic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if table_exists("artist_new_releases"):
        op.drop_table("artist_new_releases")
    if table_exists("artist_check_cache"):
        op.drop_table("artist_check_cache")


def downgrade() -> None:
    # One-way: table removed from codebase
    pass
