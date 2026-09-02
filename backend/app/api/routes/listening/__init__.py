"""What the server keeps about a listening session (ADR-0074).

Three features that used to share one 700-line `queue.py` and one `queue` tag, and a fourth that
predates the split and has rejoined them:

- `session.py` — the durable playback session (ADR-0003, ADR-0028), tag `playback-session`
- `radio.py` — what to play next (ADR-0005), tag `radio`
- `offline.py` — the precomputed offline manifest (ADR-0006), tag `offline`
- `ambient.py` — a session of harmonically-chained snippets (ADR-0106), tag `ambient`

`ambient.py` is the engine the other three were built out of: ADR-0005 took its scorer and gave it
named weight profiles, and radio, the manifest and playlist generation all rank through it. Its
routes were deleted by ADR-0077 when the web player took their only caller, and the service stayed.
It belongs here for the same reason the others do — it is a listening feature, not a resource.

**`/listening/` is a prefix, not a resource**, and ADR-0074 point 5 says so deliberately: it groups
the session under the activity it belongs to. `/session` alone would have collided with the
listening-sessions feature ADR-0070 removed, which is the confusion worth not inheriting.

No tag is set here — the leaf routers own theirs (ADR-0072 point 2), and an aggregator that also
tagged would concatenate onto all six operations.
"""

from fastapi import APIRouter

from app.api.routes.listening import ambient, offline, radio, session

router = APIRouter()
router.include_router(session.router)
router.include_router(radio.router)
router.include_router(offline.router)
router.include_router(ambient.router)

__all__ = ["ambient", "offline", "radio", "router", "session"]
