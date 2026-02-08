from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, Float, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ChangeScope, ChangeSource, ChangeStatus


class ProposedChange(Base):
    """Proposed metadata change awaiting user review.

    Changes can come from LLM suggestions, user requests, or automated lookups.
    Users can preview, approve, reject, and apply changes with control over
    scope (database only, ID3 tags, file organization).
    """

    __tablename__ = "proposed_changes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # What kind of change
    change_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "metadata", "artwork", "merge_albums", "set_compilation"
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "track", "album"

    # What's being changed (JSONB for flexibility with multiple tracks)
    target_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False
    )  # List of UUIDs as strings
    field: Mapped[str | None] = mapped_column(
        String(50)
    )  # "artist", "album_artist", "year", etc.
    old_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)  # Can be dict mapping track_id -> value
    new_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)  # The proposed new value

    # Where the change came from
    source: Mapped[ChangeSource] = mapped_column(
        Enum(ChangeSource, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    source_detail: Mapped[str | None] = mapped_column(
        String(500)
    )  # e.g., "MusicBrainz release: abc123"
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True, default=1.0)  # 0.0-1.0
    reason: Mapped[str | None] = mapped_column(Text)  # Why this change is suggested

    # How to apply the change
    scope: Mapped[ChangeScope | None] = mapped_column(
        Enum(ChangeScope, values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
        default=ChangeScope.DB_ONLY,
    )

    # Current status
    status: Mapped[ChangeStatus] = mapped_column(
        Enum(ChangeStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=ChangeStatus.PENDING,
        index=True,
    )

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, server_default=func.now(), index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
