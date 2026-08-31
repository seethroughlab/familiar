"""Create discovery_source_health, and seed a row per source.

ADR-0099 points 6, 8 and 10. The question this answers is whether a source is
*working*, which is not the question `ApiKeyStatus.tsx` answers — a source can hold
a valid key, be scheduled, run nightly, fail every time, and look identical to a
healthy one.

**The rows are seeded here rather than created on first write**, because point 8
requires "has never succeeded" to be representable. A source with no row reads as
"not a thing we track" rather than "has never worked", and those are the two
readings that must not be confused.

`discovery_batch` is seeded alongside the three upstreams because point 10 says
health has to cover the job's own outcome: the nineteen-night outage had a
perfectly healthy MusicBrainz and a dead writer, and a source-only view would have
shown all green.

Revision ID: 20260831_disc_src_health
Revises: 20260831_drop_check_prio
"""

import sqlalchemy as sa
from alembic import op

from migrations.helpers import table_exists

revision: str = "20260831_disc_src_health"
down_revision: str | None = "20260831_drop_check_prio"
branch_labels = None
depends_on = None

SOURCES = ("musicbrainz", "lastfm", "bandcamp", "discovery_batch")


def upgrade() -> None:
    if not table_exists("discovery_source_health"):
        op.create_table(
            "discovery_source_health",
            sa.Column("source", sa.String(40), primary_key=True),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.Column("last_failure_at", sa.DateTime(), nullable=True),
            sa.Column("last_failure_kind", sa.String(40), nullable=True),
            sa.Column("last_failure_detail", sa.Text(), nullable=True),
            sa.Column(
                "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "items_contributed", sa.BigInteger(), nullable=False, server_default="0"
            ),
            sa.Column("backoff_until", sa.DateTime(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    # Idempotent: re-running must not duplicate or reset a row that has since
    # recorded real successes.
    for source in SOURCES:
        op.execute(
            sa.text(
                # Values stated rather than left to column defaults. On a fresh
                # database the baseline migration builds tables with
                # `Base.metadata.create_all()`, so a model-side Python default never
                # reaches the DDL and this INSERT would violate NOT NULL.
                "INSERT INTO discovery_source_health "
                "  (source, consecutive_failures, items_contributed) "
                "VALUES (:source, 0, 0) "
                "ON CONFLICT (source) DO NOTHING"
            ).bindparams(source=source)
        )


def downgrade() -> None:
    if table_exists("discovery_source_health"):
        op.drop_table("discovery_source_health")
