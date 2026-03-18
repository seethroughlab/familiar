"""Add frontend_logs table for remote frontend log shipping.

Revision ID: 20260219_frontend_logs
Revises: 20260219_deep_analysis
Create Date: 2026-02-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.helpers import table_exists

revision = "20260219_frontend_logs"
down_revision = "20260219_deep_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if table_exists("frontend_logs"):
        return

    op.create_table(
        "frontend_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=True),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("namespace", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("client_ts", sa.DateTime(), nullable=False),
        sa.Column("server_ts", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_frontend_logs_server_ts", "frontend_logs", ["server_ts"])
    op.create_index("ix_frontend_logs_level", "frontend_logs", ["level"])
    op.create_index("ix_frontend_logs_namespace", "frontend_logs", ["namespace"])


def downgrade() -> None:
    op.drop_index("ix_frontend_logs_namespace", table_name="frontend_logs")
    op.drop_index("ix_frontend_logs_level", table_name="frontend_logs")
    op.drop_index("ix_frontend_logs_server_ts", table_name="frontend_logs")
    op.drop_table("frontend_logs")
