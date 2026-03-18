"""drop is_wishlist column from playlists

Revision ID: 20260307_drop_is_wishlist
Revises: 20250509_add_auto_download
Create Date: 2026-03-07

"""
import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

revision: str = "20260307_drop_is_wishlist"
down_revision: str | None = "20260306_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if column_exists("playlists", "is_wishlist"):
        op.drop_column("playlists", "is_wishlist")


def downgrade() -> None:
    if not column_exists("playlists", "is_wishlist"):
        op.add_column(
            "playlists",
            sa.Column("is_wishlist", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
