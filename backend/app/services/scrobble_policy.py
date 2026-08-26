"""When a listening event is worth scrobbling (ADR-0030).

Pure, and separate from the endpoints, because this is the part that has to be right and the part
worth testing without a request in hand.

**Last.fm's rule is not Familiar's.** A play in Familiar means the track reached its end — ADR-0004
point 4 keeps skips off `play_count` deliberately. Last.fm asks for half. The gap between the two is
a track someone listened to most of and then skipped, which is ordinary listening rather than an edge
case, and it is why this is computed from the event's own numbers instead of from which endpoint
delivered it.
"""

from __future__ import annotations

# Last.fm's published guidance. Both must hold.
MINIMUM_SECONDS = 30
"""Below this, Last.fm does not want it however short the track is."""

HALFWAY_CAP_SECONDS = 240
"""Half the track, but never more than four minutes — so an hour-long mix scrobbles at four."""


def should_scrobble(
    played_seconds: float | None,
    track_duration: float | None,
) -> bool:
    """Whether this much listening counts as a scrobble.

    ``played_seconds`` is forward progress, not wall-clock time between start and stop: pausing for
    an hour does not earn a scrobble, and the clients already report it that way.

    A missing duration is treated as "long enough", because the only threshold left is the 30-second
    floor and refusing on incomplete metadata would silently drop scrobbles for tracks the server
    simply has not analysed.
    """
    if played_seconds is None or played_seconds < MINIMUM_SECONDS:
        return False
    if track_duration is None or track_duration <= 0:
        return True
    return played_seconds >= min(track_duration / 2, HALFWAY_CAP_SECONDS)
