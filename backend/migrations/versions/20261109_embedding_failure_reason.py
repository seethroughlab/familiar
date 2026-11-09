"""Embedding failures carry a reason and an attempt count (ADR-0172).

An embedding failure used to be retried every 24 hours for ever: on the NAS, four files ffmpeg
cannot decode failed every day. `embedding_failure_reason` is a stable code and
`embedding_attempts` counts tries; `app/services/analysis_lifecycle.py` stops retrying a permanent
reason, or after three attempts.

Existing failures are backfilled from the message they already store, so the undecodable ones stop
at the first sync after this deploys rather than three days later.

Revision ID: 20261109_embed_failure_reason
Revises: 20261102_drop_claims_health_row
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.helpers import column_exists

revision: str = "20261109_embed_failure_reason"
down_revision: str | None = "20261102_drop_claims_health_row"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not column_exists("track_analysis", "embedding_failure_reason"):
        op.add_column(
            "track_analysis", sa.Column("embedding_failure_reason", sa.String(32), nullable=True)
        )
    if not column_exists("track_analysis", "embedding_attempts"):
        op.add_column(
            "track_analysis",
            sa.Column("embedding_attempts", sa.Integer(), nullable=False, server_default="0"),
        )
    # Mirrors `analysis_lifecycle.classify` for the two permanent reasons; anything else stays a
    # transient failure with one attempt.
    op.execute(
        """
        UPDATE track_analysis
        SET embedding_attempts = GREATEST(embedding_attempts, 1),
            embedding_failure_reason = CASE
                WHEN lower(embedding_error) LIKE '%could not decode%'
                  OR lower(embedding_error) LIKE '%invalid data found%' THEN 'undecodable'
                WHEN lower(embedding_error) LIKE '%file not found%'
                  OR lower(embedding_error) LIKE '%no such file%' THEN 'file_missing'
                ELSE 'error'
            END
        WHERE embedding_failed_at IS NOT NULL AND embedding_failure_reason IS NULL
        """
    )


def downgrade() -> None:
    if column_exists("track_analysis", "embedding_attempts"):
        op.drop_column("track_analysis", "embedding_attempts")
    if column_exists("track_analysis", "embedding_failure_reason"):
        op.drop_column("track_analysis", "embedding_failure_reason")
