"""Spotify import model.

Stores parsed Spotify data export + pre-computed match results as JSONB.
One row per profile — re-importing replaces the previous import.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SpotifyImport(Base):
    """Parsed Spotify data export for a profile."""

    __tablename__ = "spotify_imports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    spotify_username: Mapped[str | None] = mapped_column(String(255))
    favorites: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    playlists: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    streaming_stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    match_results: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
