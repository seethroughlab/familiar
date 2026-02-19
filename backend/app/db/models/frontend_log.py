"""Frontend log model for remote log shipping."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class FrontendLog(Base):
    """Stores log entries shipped from the frontend for remote diagnosis."""

    __tablename__ = "frontend_logs"
    __table_args__ = (
        Index("ix_frontend_logs_server_ts", "server_ts"),
        Index("ix_frontend_logs_level", "level"),
        Index("ix_frontend_logs_namespace", "namespace"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID | None] = mapped_column()  # No FK -- survives profile deletion
    level: Mapped[str] = mapped_column(String(10))
    namespace: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    client_ts: Mapped[datetime] = mapped_column(DateTime)
    server_ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
