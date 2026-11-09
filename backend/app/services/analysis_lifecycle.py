"""What analysis work exists, and when a failure stops being retried (ADR-0172).

**One definition, used by the queue and by the count.** Before ADR-0172 the sync loop counted
pending features as *every* `Track` row minus the current analyses, while
`queue_tracks_for_features` queued only `ACTIVE` tracks. On the NAS 30 tracks (27 `skipped`,
2 `missing`, 1 `pending_deletion`) were counted forever and queued never. Every two-hourly sync
therefore spun its features and embeddings phases for two minutes until the churn guard stopped
them (`queue_churn_limit_exceeded:61/60:300s`), on a library with nothing to do. Here the population
a phase is responsible for, and which of it may be tried now, are each written once.

**A failure ends somewhere.** An embedding failure used to wait 24 hours and be retried for ever. On
the NAS, four files ffmpeg cannot decode were retried every day and failed every day. A failure now
carries a reason code and an attempt count (`TrackAnalysis.embedding_failure_reason`,
`embedding_attempts`):

- **permanent** reasons (`undecodable`, `file_missing`) are not retried. A changed file is
  re-analysed anyway, because the scanner deletes its `TrackAnalysis` row and the failure goes
  with it;
- any other reason is retried after `RETRY_AFTER`, at most `MAX_ATTEMPTS` times in all.

Features need no such columns: a feature failure already marks the track's features current
(`_ensure_track_analysis_row`), so it is terminal on the first attempt.

**The lifecycle**, for each phase, of a track the phase is responsible for:

- *complete*: the current version is stored;
- *failed*: it failed, and will not be tried again until something changes;
- *retry-wait*: it failed, and will be tried again after `RETRY_AFTER`;
- *queued* or *active*: everything else, which the queue may pick up now.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_VERSION, FEATURES_VERSION
from app.db.models import Track, TrackAnalysis, TrackStatus
from app.utils.time import utcnow

RETRY_AFTER = timedelta(hours=24)
MAX_ATTEMPTS = 3


class FailureReason(str, Enum):
    """Stable codes for why a phase failed; logs and status name these, never the prose."""

    UNDECODABLE = "undecodable"
    FILE_MISSING = "file_missing"
    WORKER_CRASHED = "worker_crashed"
    TIMEOUT = "timeout"
    ERROR = "error"


PERMANENT = frozenset({FailureReason.UNDECODABLE, FailureReason.FILE_MISSING})


def classify(error: str | None) -> FailureReason:
    """The reason code for a failure message.

    Matched on the messages the analysis code itself raises, which is the one place prose is read,
    so that nothing downstream has to.
    """
    text = (error or "").lower()
    if "could not decode" in text or "invalid data found" in text:
        return FailureReason.UNDECODABLE
    if "file not found" in text or "no such file" in text:
        return FailureReason.FILE_MISSING
    if "terminated abruptly" in text or "brokenprocesspool" in text or "process pool" in text:
        return FailureReason.WORKER_CRASHED
    if "timed out" in text or "timeout" in text:
        return FailureReason.TIMEOUT
    return FailureReason.ERROR


def is_terminal(reason: FailureReason, attempts: int) -> bool:
    """Whether a failure with this reason, after this many attempts, is never retried."""
    return reason in PERMANENT or attempts >= MAX_ATTEMPTS


def retry_cutoff(now: datetime | None = None) -> datetime:
    """A failure before this instant has waited long enough to be tried again."""
    return (now or utcnow()) - RETRY_AFTER


# ── Who each phase is responsible for ───────────────────────────────────────────────────────────


def in_library() -> ColumnElement[bool]:
    """Tracks analysis is for: in the library and present. `skipped`, `missing`, `pending_review`
    and `pending_deletion` are not analysed, so they are never pending either."""
    return and_(Track.status == TrackStatus.ACTIVE, Track.missing_since.is_(None))


def features_needed() -> ColumnElement[bool]:
    """Needs features. Requires `outerjoin(TrackAnalysis)`."""
    return and_(
        in_library(),
        or_(TrackAnalysis.id.is_(None), TrackAnalysis.features_version < FEATURES_VERSION),
    )


def features_queueable(cutoff: datetime) -> ColumnElement[bool]:
    """Needs features and may be tried now. Requires `outerjoin(TrackAnalysis)`."""
    return and_(
        features_needed(),
        or_(Track.analysis_failed_at.is_(None), Track.analysis_failed_at < cutoff),
    )


def embeddings_needed() -> ColumnElement[bool]:
    """Has current features and needs an embedding. Requires `join(TrackAnalysis)`."""
    return and_(
        in_library(),
        TrackAnalysis.features_version >= FEATURES_VERSION,
        TrackAnalysis.embedding_version < EMBEDDING_VERSION,
    )


def embeddings_retryable(cutoff: datetime) -> ColumnElement[bool]:
    """Never failed, or failed for a transient reason, fewer than `MAX_ATTEMPTS` times, long enough
    ago. A failure recorded before reason codes existed has no reason and counts as transient."""
    return or_(
        TrackAnalysis.embedding_failed_at.is_(None),
        and_(
            or_(
                TrackAnalysis.embedding_failure_reason.is_(None),
                TrackAnalysis.embedding_failure_reason.notin_([r.value for r in PERMANENT]),
            ),
            TrackAnalysis.embedding_attempts < MAX_ATTEMPTS,
            TrackAnalysis.embedding_failed_at < cutoff,
        ),
    )


def embeddings_queueable(cutoff: datetime) -> ColumnElement[bool]:
    """Needs an embedding and may be tried now. Requires `join(TrackAnalysis)`."""
    return and_(embeddings_needed(), embeddings_retryable(cutoff))


# ── What remains: the sync loop's exit condition ────────────────────────────────────────────────


async def features_remaining(db: AsyncSession, now: datetime | None = None) -> int:
    """Tracks the features phase could still do now: exactly what its queue would take.

    A sync phase is finished when this is zero. Counting anything the queue cannot take (another
    status, a failure waiting out its window) is how the loop spun until the churn guard.
    """
    query = (
        select(func.count(Track.id))
        .outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        .where(features_queueable(retry_cutoff(now)))
    )
    return (await db.execute(query)).scalar() or 0


async def embeddings_remaining(db: AsyncSession, now: datetime | None = None) -> int:
    """Tracks the embeddings phase could still do now: exactly what its queue would take."""
    query = (
        select(func.count(Track.id))
        .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        .where(embeddings_queueable(retry_cutoff(now)))
    )
    return (await db.execute(query)).scalar() or 0
