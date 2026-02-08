import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PluginType(enum.Enum):
    """Type of plugin - visualizer or library browser."""

    VISUALIZER = "visualizer"
    BROWSER = "browser"


class Plugin(Base):
    """Installed plugins for visualizers and library browsers.

    Plugins are fetched from GitHub repositories and stored locally.
    Each plugin provides a pre-built JavaScript bundle that registers
    itself with the app's visualizer or browser registry.
    """

    __tablename__ = "plugins"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Plugin identity (from manifest)
    plugin_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    plugin_type: Mapped[PluginType] = mapped_column(
        Enum(PluginType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text)

    # Author info
    author_name: Mapped[str | None] = mapped_column(String(255))
    author_url: Mapped[str | None] = mapped_column(String(500))

    # Source repository
    repository_url: Mapped[str] = mapped_column(String(500), nullable=False)
    installed_from: Mapped[str] = mapped_column(String(500), nullable=False)  # Full URL used

    # Local storage
    bundle_path: Mapped[str] = mapped_column(String(500), nullable=False)
    bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA256

    # Compatibility
    api_version: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    min_familiar_version: Mapped[str | None] = mapped_column(String(20))

    # Status
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True)
    load_error: Mapped[str | None] = mapped_column(Text)  # Last error if failed to load

    # Full manifest (JSONB for flexibility)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=dict)

    # Timestamps
    installed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=func.now(), onupdate=func.now()
    )
    last_update_check: Mapped[datetime | None] = mapped_column(DateTime)
