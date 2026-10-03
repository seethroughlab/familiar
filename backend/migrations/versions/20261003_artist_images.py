"""Artist photo galleries (ADR-0149).

`artist_images` holds many photos per artist, with the attribution each licence requires.
`artists.image_chosen` marks a main picture the owner picked, which the resolver then leaves alone;
`artists.gallery_fetched_at` says when the gallery was last fetched, so a fetch is scheduled only
when it is missing or stale.

Revision ID: 20261003_artist_images
Revises: 20260929_kv_store
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import column_exists, index_exists, table_exists

revision: str = "20261003_artist_images"
down_revision: str | None = "20260929_kv_store"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not column_exists("artists", "image_chosen"):
        op.add_column(
            "artists",
            sa.Column("image_chosen", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    if not column_exists("artists", "gallery_fetched_at"):
        op.add_column("artists", sa.Column("gallery_fetched_at", sa.DateTime(), nullable=True))

    if not table_exists("artist_images"):
        op.create_table(
            "artist_images",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "artist_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("artists.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column("source_id", sa.Text(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("thumb_url", sa.Text(), nullable=False),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("author", sa.Text(), nullable=True),
            sa.Column("license", sa.Text(), nullable=True),
            sa.Column("license_url", sa.Text(), nullable=True),
            sa.Column("page_url", sa.Text(), nullable=True),
            sa.Column("rank", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("fetched_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("artist_id", "source", "source_id", name="uq_artist_images_source"),
        )
    if not index_exists("ix_artist_images_artist_rank"):
        op.create_index("ix_artist_images_artist_rank", "artist_images", ["artist_id", "rank"])


def downgrade() -> None:
    if index_exists("ix_artist_images_artist_rank"):
        op.drop_index("ix_artist_images_artist_rank", table_name="artist_images")
    if table_exists("artist_images"):
        op.drop_table("artist_images")
    if column_exists("artists", "gallery_fetched_at"):
        op.drop_column("artists", "gallery_fetched_at")
    if column_exists("artists", "image_chosen"):
        op.drop_column("artists", "image_chosen")
