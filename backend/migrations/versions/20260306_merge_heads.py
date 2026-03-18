"""Pin head after feature shelf removals.

Revision ID: 20260306_merge_heads
Revises: 20260306_drop_spt_ext, 20260227_empty_wishlist
Create Date: 2026-03-06
"""


revision = "20260306_merge_heads"
down_revision = ("20260306_drop_spt_ext", "20260227_empty_wishlist")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    # One-way: merge migration
    pass
