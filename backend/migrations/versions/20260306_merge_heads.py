"""Merge wishlist and drop-features heads.

Revision ID: 20260306_merge_heads
Revises: 20260227_empty_wishlist, 20260306_drop_spt_ext
Create Date: 2026-03-06
"""

from alembic import op

revision = "20260306_merge_heads"
down_revision = ("20260227_empty_wishlist", "20260306_drop_spt_ext")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
