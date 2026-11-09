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

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_VERSION, FEATURES_VERSION, MELODIC_VERSION, MOOD_TAGS_VERSION
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


# ── The later phases: no retry state, because their failures are terminal ────────────────────────
#
# Each needs the phase before it, so a track whose earlier phase is not done is *waiting*, not
# pending. Melodic marks its version current on failure; mood tags derive from the embedding and do
# not touch the file; deep backfill is a one-off that empties itself.


def features_current() -> ColumnElement[bool]:
    return TrackAnalysis.features_version >= FEATURES_VERSION


def backfill_queueable() -> ColumnElement[bool]:
    """Requires `join(TrackAnalysis)`."""
    return and_(in_library(), features_current(), TrackAnalysis.analysis_detail.is_(None))


def melodic_queueable() -> ColumnElement[bool]:
    """Requires `join(TrackAnalysis)`."""
    return and_(
        in_library(),
        features_current(),
        TrackAnalysis.analysis_detail.is_not(None),
        TrackAnalysis.melodic_version < MELODIC_VERSION,
    )


def mood_tags_queueable() -> ColumnElement[bool]:
    """Requires `join(TrackAnalysis)`."""
    return and_(
        in_library(),
        TrackAnalysis.embedding.is_not(None),
        TrackAnalysis.mood_tags_version < MOOD_TAGS_VERSION,
    )


def _embedding_terminal() -> ColumnElement[bool]:
    """Coalesced, because a failure recorded before reason codes has a NULL reason, and
    `NOT (NULL IN …)` is NULL: negated, the row would be neither retrying nor failed."""
    return or_(
        func.coalesce(TrackAnalysis.embedding_failure_reason, "").in_([r.value for r in PERMANENT]),
        func.coalesce(TrackAnalysis.embedding_attempts, 0) >= MAX_ATTEMPTS,
    )


# ── Counts by lifecycle state: the one status model (ADR-0172 point 6) ─────────────────────────


PHASES = ("features", "embeddings", "deep_backfill", "melodic", "mood_tags")


@dataclass(frozen=True)
class PhaseCounts:
    """One phase's tracks, by state. The states partition `total`: every track in the library is
    in exactly one of them.

    - `complete`: the current version is stored;
    - `queued`: may be worked on now (including what a worker has in hand);
    - `retrying`: failed, and will be tried again after the retry window;
    - `failed`: failed, and will not be tried again until the file changes;
    - `waiting`: an earlier phase has not finished for it.

    `pending` is `queued + retrying`: the work that will still happen. It is the number every
    endpoint reports as pending, so no two can disagree again.
    """

    phase: str
    total: int
    complete: int
    queued: int
    retrying: int
    failed: int
    waiting: int

    @property
    def pending(self) -> int:
        return self.queued + self.retrying

    @property
    def percent(self) -> float:
        return round(self.complete / self.total * 100, 1) if self.total else 100.0

    def as_dict(self) -> dict[str, int | float | str]:
        return {**asdict(self), "pending": self.pending, "percent": self.percent}


def _states(now: datetime | None) -> dict[str, dict[str, ColumnElement[bool]]]:
    cutoff = retry_cutoff(now)
    features_failed = Track.analysis_failed_at.is_not(None)
    embedding_failed = TrackAnalysis.embedding_failed_at.is_not(None)
    return {
        "features": {
            "complete": and_(features_current(), ~features_failed),
            # A feature failure marks the version current, so it is final on the first attempt.
            "failed": and_(features_current(), features_failed),
            "retrying": and_(features_needed(), Track.analysis_failed_at >= cutoff),
            "queued": features_queueable(cutoff),
        },
        "embeddings": {
            "complete": and_(features_current(), TrackAnalysis.embedding_version >= EMBEDDING_VERSION),
            "failed": and_(embeddings_needed(), embedding_failed, _embedding_terminal()),
            "retrying": and_(
                embeddings_needed(),
                embedding_failed,
                ~_embedding_terminal(),
                TrackAnalysis.embedding_failed_at >= cutoff,
            ),
            "queued": embeddings_queueable(cutoff),
        },
        "deep_backfill": {
            "complete": and_(features_current(), TrackAnalysis.analysis_detail.is_not(None)),
            "queued": backfill_queueable(),
        },
        "melodic": {
            "complete": and_(features_current(), TrackAnalysis.melodic_version >= MELODIC_VERSION),
            "queued": melodic_queueable(),
        },
        "mood_tags": {
            "complete": TrackAnalysis.mood_tags_version >= MOOD_TAGS_VERSION,
            "queued": mood_tags_queueable(),
        },
    }


async def phase_counts(db: AsyncSession, now: datetime | None = None) -> dict[str, PhaseCounts]:
    """Every phase's counts by state, in one query over the library.

    `/health/system`, `/health/workers`, `/library/stats`, `/library/analysis/status` and the
    Analysis page all read this; a number that answers a different question gets a different name.
    """
    states = _states(now)
    columns = [func.count(Track.id).label("total")]
    for phase, conditions in states.items():
        for state, condition in conditions.items():
            columns.append(func.count(Track.id).filter(condition).label(f"{phase}.{state}"))
    query = (
        select(*columns)
        .select_from(Track)
        .outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        .where(in_library())
    )
    row = (await db.execute(query)).one()._mapping
    total = row["total"]
    counts: dict[str, PhaseCounts] = {}
    for phase, conditions in states.items():
        got = {state: row[f"{phase}.{state}"] for state in conditions}
        complete, queued = got["complete"], got["queued"]
        retrying, failed = got.get("retrying", 0), got.get("failed", 0)
        counts[phase] = PhaseCounts(
            phase=phase,
            total=total,
            complete=complete,
            queued=queued,
            retrying=retrying,
            failed=failed,
            waiting=total - complete - queued - retrying - failed,
        )
    return counts


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


async def queueable_count(db: AsyncSession, condition: ColumnElement[bool]) -> int:
    """How many tracks a later phase's queue could take now (`backfill_queueable` and the rest)."""
    query = (
        select(func.count(Track.id))
        .select_from(Track)
        .join(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        .where(condition)
    )
    return (await db.execute(query)).scalar() or 0
