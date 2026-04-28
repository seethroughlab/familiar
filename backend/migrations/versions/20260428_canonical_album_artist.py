"""Add tracks.canonical_album_artist_id (Pass 3).

Pass 2 cut the ``album_artist`` OR clause from ``get_artist_detail``
(it was re-introducing the duplicate-tile bug from a different angle).
The known cost was ~1054 tracks losing visibility under the right
canonical artist — diacritic-only mismatches (Björk / Múm / Röyksopp /
µ-Ziq), compilation/soundtrack credits ("Original Soundtrack"), and
DJ-mix album-level tags.

Pass 3 fixes that by treating ``album_artist`` as an alias source: the
scanner now resolves it through the same ``resolve_canonical_artist``
chain and stores the result in ``tracks.canonical_album_artist_id``.
``get_artist_detail`` then OR-matches on both canonical FKs to surface
those tracks under the right artist again.

Revision ID: 20260428_canonical_album_artist
Revises: 20260428_canonical_artists
Create Date: 2026-04-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from migrations.helpers import column_exists, index_exists

revision: str = "20260428_canonical_album_artist"
down_revision: str | None = "20260428_canonical_artists"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not column_exists("tracks", "canonical_album_artist_id"):
        op.add_column(
            "tracks",
            sa.Column(
                "canonical_album_artist_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("artists.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    if not index_exists("ix_tracks_canonical_album_artist_id"):
        op.create_index(
            "ix_tracks_canonical_album_artist_id",
            "tracks",
            ["canonical_album_artist_id"],
        )


def downgrade() -> None:
    """No-op per repo migration policy."""
    pass
