from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class MixTape(Base):
    """User-rendered mixtape: a single MP3 file edited together from a playlist.

    Always tied back to the source playlist (static or smart) so we can
    re-render and so the UI can group by source. Tracks are snapshotted
    at render time as `track_ids` — smart playlists may resolve to a
    different set on a future render.
    """

    __tablename__ = "mixtapes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Optional curator credit; rendered as "by <byline>" on the cover and
    # written to TPE2/TPE4 ID3 frames.
    byline: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Exactly one of these is set.
    source_playlist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("playlists.id", ondelete="SET NULL"), nullable=True
    )
    source_smart_playlist_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("smart_playlists.id", ondelete="SET NULL"), nullable=True
    )

    # Snapshot of the track UUIDs in render order.
    track_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # None = no crossfade; otherwise crossfade duration per transition.
    crossfade_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 'pending' | 'rendering' | 'ready' | 'failed'
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    audio_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    tracklist_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    bundle_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    profile: Mapped["Profile"] = relationship()  # type: ignore[name-defined]  # noqa: F821
