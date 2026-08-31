"""Music you own and have not heard, ranked by what you actually listen to (ADR-0101).

**The single largest discovery opportunity Familiar has, and the one a streaming
service structurally cannot compete on.** Measured on the production library:
23,683 of 26,434 tracks — 90% — have never been played. Spotify cannot recommend
from a collection it cannot see, and cannot know you bought something in 2014 and
never played it.

This replaces the Discover dashboard's `unheard_tracks` and `deep_cuts`, which were
`ORDER BY random()` over tracks by artists you already play. Two limits there, and
the second is the interesting one: the ordering was not ranking at all, and the
candidate set could never contain an artist you had not already listened to. A
record that sounds exactly like your favourite album was unreachable if you had
never played that artist.

**The mechanism is ADR-0093's, pointed at a different collection**, and this module
is deliberately thin because of that. Seeds are what you play; the exclusion set is
what you have heard; the result is agreement between seeds, never their average.
That last point is load-bearing and was learned the hard way — see
`collection_suggestions`, which records that averaging embeddings was tried at two
scales and returned the library's most generically average music both times.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProfilePlayHistory, Track
from app.services.collection_suggestions import (
    SEED_SAMPLE_CAP,
    Suggestion,
    suggest_for_collection,
)

logger = logging.getLogger(__name__)

#: Plays above which a track counts as "heard" and stops being a candidate.
#:
#: Not 1. Excluding everything with any play history would drop the case the old
#: `deep_cuts` list existed for — a track played once, years ago, and forgotten — and
#: this section replaces that list rather than joining it. Three is low enough that
#: anything genuinely in rotation is excluded, and high enough that a track you
#: sampled once can still come back.
HEARD_THRESHOLD = 3

#: **A candidate needs features, not just an embedding.** `collection_suggestions`
#: requires `TrackAnalysis.energy` to be present — a track with no features cannot be
#: scored — so a track analysed for embeddings but not features is invisible here.
#: Measured on the production library 2026-08-31: 736 of 26,471 embedded tracks, or
#: 2.8%. Small enough to accept and specific enough to be worth writing down, because
#: the symptom is a track that never appears and no error anywhere.


async def suggest_rediscovery(
    db: AsyncSession,
    *,
    profile_id: UUID,
    limit: int = 15,
) -> tuple[list[Suggestion], int]:
    """Unheard library tracks ranked against recent listening.

    Returns the suggestions and the number of seeds behind them, because a caller
    showing an empty list has to be able to say *why* — no listening history and
    nothing similar found are different answers, and ADR-0101 point 7 says a surface
    returning nothing is a defect rather than a silence.
    """
    # Most-recent-first: `suggest_for_collection` samples from the head, so this is
    # what makes the suggestions track current taste rather than all-time taste.
    seed_rows = (
        await db.execute(
            select(ProfilePlayHistory.track_id)
            .join(Track, ProfilePlayHistory.track_id == Track.id)
            .where(
                ProfilePlayHistory.profile_id == profile_id,
                Track.active_filter(),
            )
            .order_by(ProfilePlayHistory.last_played_at.desc().nullslast())
        )
    ).scalars().all()
    seed_ids = list(seed_rows)

    if not seed_ids:
        return [], 0

    # Exclude what has been heard, which is a wider set than the seeds — ADR-0093
    # point 4: once the seed is a sample, "exclude the seed" and "exclude what you
    # already have" stop being the same set, and the difference shows up as a
    # suggestion the listener plays every week.
    heard_ids = set(
        (
            await db.execute(
                select(ProfilePlayHistory.track_id).where(
                    ProfilePlayHistory.profile_id == profile_id,
                    ProfilePlayHistory.play_count >= HEARD_THRESHOLD,
                )
            )
        )
        .scalars()
        .all()
    )

    suggestions = await suggest_for_collection(
        db,
        seed_track_ids=seed_ids[:SEED_SAMPLE_CAP],
        exclude_track_ids=heard_ids,
        # Excluded by id at three plays, but *any* play makes a recording known well
        # enough that a second file of it is not a discovery. Keeping these separate
        # is what lets a track played twice come back as itself — a deep cut — while
        # its duplicate does not.
        duplicate_key_ids=set(seed_ids),
        # Carries ADR-0004's rejection signal into discovery (ADR-0101 point 4):
        # `_demote_rejected` reads it, so a track the listener has already dismissed
        # does not come back at the top of the list.
        profile_id=profile_id,
        limit=limit,
    )
    return suggestions, len(seed_ids)
