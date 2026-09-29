"""The key/value store that stands in for Redis when there is none (ADR-0133).

Two tables because Redis has two shapes here: plain values (progress, locks, cursors, caches) and
capped lists (the event log, task failures, backup history). A list's expiry lives on its
`kv_store` row, whose `kind` says which shape the key is.

These tables are only written when `REDIS_URL` is unset. They exist everywhere so that the schema
does not depend on configuration.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class KVEntry(Base):
    __tablename__ = "kv_store"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    # "string" or "list". A list's values live in `kv_list`; this row carries its expiry.
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    value: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # NULL means no expiry, as in Redis.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KVListItem(Base):
    __tablename__ = "kv_list"
    __table_args__ = (Index("ix_kv_list_key_seq", "key", "seq"),)

    # Higher seq is nearer the head: LPUSH takes the next value from the sequence.
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(
        Text, ForeignKey("kv_store.key", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
