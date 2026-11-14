"""How far each profile has looked at new music (ADR-0179).

One row per profile: `seen_through` is the newest discovered release it has been shown, and the
digest columns are ADR-0182's weekly reminder. Rows are created on a profile's first what's-new
read, so this migration only makes the table.

Revision ID: 20261114_profile_discovery_state
Revises: 20261109_embed_failure_reason
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import table_exists

revision: str = "20261114_profile_discovery_state"
down_revision: str | None = "20261109_embed_failure_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("profile_discovery_state"):
        op.create_table(
            "profile_discovery_state",
            sa.Column(
                "profile_id",
                sa.UUID(),
                sa.ForeignKey("profiles.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("seen_through", sa.DateTime(), nullable=True),
            sa.Column("digest_through", sa.DateTime(), nullable=True),
            sa.Column("digest_sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    if table_exists("profile_discovery_state"):
        op.drop_table("profile_discovery_state")
