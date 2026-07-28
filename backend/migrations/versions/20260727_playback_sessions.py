"""Add playback_sessions and playback_session_archive for the server-owned queue.

The playback queue lived only on the client, so nothing could hand a queue from one
device to another and every new platform had to reimplement the shuffle, consume and
lazy-reservoir bookkeeping. These tables make the server the source of truth for the
durable queue; clients keep an authoritative local replica and never block playback on
it (ADR-0003).

Keyed by profile alone. There is no device dimension: `Profile.device_id` is a legacy
column with no readers, so device keying would mean inventing an identity the codebase
does not have — the same wall ADR-0006 hit and routed around.

The archive table exists because the conflict rule is "later write wins, and nothing is
destroyed". A queue that loses a conflict is retained and can be restored.

Revision ID: 20260727_playback_sessions
Revises: 20260726_play_events
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import index_exists, table_exists

revision: str = "20260727_playback_sessions"
down_revision: str | None = "20260726_play_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _payload_columns() -> list[sa.Column]:
    """The queue itself — identical on the live table and the archive.

    Mirrors the `PlaybackSessionPayload` mixin. An archived row has to be able to replace
    a live one field for field, so the two column sets must not drift.
    """
    return [
        # JSONB rather than ARRAY(UUID): every other list-of-IDs column in this schema is
        # JSONB (see mixtapes.track_ids), and nothing queries into them.
        sa.Column("track_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Index of the current track; -1 when the queue is empty.
        sa.Column("cursor", sa.Integer(), nullable=False, server_default=sa.text("-1")),
        sa.Column("shuffle_order", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("shuffle_index", sa.Integer(), nullable=False, server_default=sa.text("-1")),
        sa.Column("shuffle", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # 'off' | 'all' | 'one'
        sa.Column("repeat", sa.String(length=8), nullable=False, server_default="off"),
        sa.Column("consume", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # {type, id?, filters?}. Stored whole because toggleShuffle replays `filters`
        # verbatim; `type` uses the client's queue-source vocabulary, which deliberately
        # excludes the 'radio' and 'ambient' of PlayContext.
        sa.Column("queue_source", postgresql.JSONB(), nullable=True),
        # The lazy reservoir. Only a ~50-track window of it is materialised into
        # track_ids; without it a restored queue silently ends after that window.
        sa.Column("reservoir_ids", postgresql.JSONB(), nullable=True),
        sa.Column("reservoir_cursor", sa.Integer(), nullable=False, server_default=sa.text("-1")),
        # Lets a write omit reservoir_ids when unchanged, rather than shipping ~1 MB of
        # UUIDs with every cursor advance.
        sa.Column("reservoir_hash", sa.String(length=64), nullable=True),
        # Without this a handoff resumes at the top of the track, not where the listener was.
        sa.Column("position_seconds", sa.Float(), nullable=False, server_default=sa.text("0")),
    ]


def upgrade() -> None:
    if not table_exists("playback_sessions"):
        op.create_table(
            "playback_sessions",
            # Profile alone is the primary key — one live queue per profile, so handoff
            # needs no explicit transfer step.
            sa.Column(
                "profile_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("profiles.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            *_payload_columns(),
            # Bumped on every accepted write so a client can detect a stale replica.
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    if not table_exists("playback_session_archive"):
        op.create_table(
            "playback_session_archive",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "profile_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("profiles.id", ondelete="CASCADE"),
                nullable=False,
            ),
            *_payload_columns(),
            # When the losing device last wrote it, not when it was archived — the latter
            # would lose the only clue about which queue this was.
            sa.Column("superseded_at", sa.DateTime(), nullable=False),
            sa.Column(
                "archived_at",
                sa.DateTime(),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    # Listing a profile's restorable queues, newest first.
    if not index_exists("ix_playback_session_archive_profile"):
        op.create_index(
            "ix_playback_session_archive_profile",
            "playback_session_archive",
            ["profile_id", "archived_at"],
        )


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
