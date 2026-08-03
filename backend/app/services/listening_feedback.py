"""Which `PlayEvent` rows may be used to reason about *how much* of a track was heard.

ADR-0004 leaves the completion-ratio threshold for `skipped` to be decided empirically
"once data exists". Data exists — but not all of it means what it says, and the boundary
is a date rather than anything recorded on the row.

**What happened.** Until `familiar` #57 the web client delivered a play the moment
listening crossed ``min(duration / 2, 4 min)`` and sent ``completion_ratio`` as measured
*at that instant*. Nothing revised it afterwards, so a web play landed at almost exactly
0.5 whether the listener heard half the track or all of it. Measured on the live database
on 2026-08-01: **289 of 357 completed events sat in the 0.5–0.6 bucket**, against native
client rows correctly reading 0.95–1.00.

**Why a date and not a client column.** `play_events` records no client, and `context`
does not stand in for one — the web derives it from the queue source and sends `library`
for a library queue, exactly as the native app does. So the good native rows from before
the fix cannot be separated from the bad web rows beside them. Selecting on the ratio
itself would be circular: it is the variable being measured. A date cutoff is the only
separator that does not assume the answer, and it costs the native rows in that window.

**The damage is not limited to the ratio.** Because a play was *reported* at the halfway
mark, a track abandoned at 55% was recorded as a completion at ~0.5 rather than as a skip.
So before the cutoff the `outcome` labels are unreliable too, and skips are *under*-counted
rather than merely imprecise.

**What is still safe to use from before the cutoff.** Rows recorded as `skipped` or
`rejected` describe real abandonments and keep their ratios; they are simply an incomplete
census. `ambient._negative_signal` counts exactly those two outcomes over a rolling 90-day
window, so the recommender was never poisoned — it has been running on a slightly weaker
negative signal, which heals as the window passes the cutoff. That is the reason these rows
are kept rather than deleted.

Anything reasoning about `completion_ratio` or trusting `outcome == 'completed'` must go
through `trustworthy_feedback_only` below.
"""

from datetime import datetime

from sqlalchemy import ColumnElement

from app.db.models import PlayEvent

# The first day whose events were all recorded by clients that report at the end of a
# track. `familiar` #57 shipped 2026-08-01; every row from that date on has been verified
# against the live database as completions clustering at ≥0.9 and skips at ≤0.1.
#
# Naive UTC, because `PlayEvent.started_at` is TIMESTAMP WITHOUT TIME ZONE — see
# `app.utils.time.utcnow` for why the whole codebase is naive here.
FEEDBACK_TRUSTWORTHY_SINCE = datetime(2026, 8, 1)


def trustworthy_feedback_only() -> ColumnElement[bool]:
    """The filter every completion-ratio query must apply.

    A function rather than a bare comparison so the reason travels with the call: a
    `WHERE started_at >= <date>` sitting in an analysis script explains nothing, and the
    next person to write one would reasonably remove it.
    """
    return PlayEvent.started_at >= FEEDBACK_TRUSTWORTHY_SINCE
