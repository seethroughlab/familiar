"""Create `kv_store` and `kv_list`, the Postgres stand-in for Redis (ADR-0133).

Only written when `REDIS_URL` is unset, which is how a server outside Docker runs. Created on every
database regardless, so the schema never depends on configuration. Ordinary logged tables, not
`UNLOGGED`: the sync rotation cursor and Soulseek "settled" markers live here, and the compose Redis
already keeps them across restarts on its `redis_data` volume.

Revision ID: 20260929_kv_store
Revises: 20260831_seed_listenbrainz
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import index_exists, table_exists

revision: str = "20260929_kv_store"
down_revision: str | None = "20260831_seed_listenbrainz"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not table_exists("kv_store"):
        op.create_table(
            "kv_store",
            sa.Column("key", sa.Text(), primary_key=True),
            sa.Column("kind", sa.String(10), nullable=False),
            sa.Column("value", sa.LargeBinary(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not table_exists("kv_list"):
        op.create_table(
            "kv_list",
            sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "key",
                sa.Text(),
                sa.ForeignKey("kv_store.key", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("value", sa.LargeBinary(), nullable=False),
        )
    if not index_exists("ix_kv_list_key_seq"):
        op.create_index("ix_kv_list_key_seq", "kv_list", ["key", "seq"])


def downgrade() -> None:
    # Everything here is state Redis would also have held: progress, locks, caches, a cursor.
    # Dropping it costs a re-sync at worst.
    op.drop_index("ix_kv_list_key_seq", table_name="kv_list")
    op.drop_table("kv_list")
    op.drop_table("kv_store")
