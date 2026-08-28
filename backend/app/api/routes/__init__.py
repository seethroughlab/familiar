"""API routes package — one aggregated router for the whole v1 surface.

**Everything is registered here, once** (ADR-0072 point 6). `main.py` mounts the result with a
single `include_router`, so a concern shared by every route is expressed in one place instead of
being repeated on a list of near-identical lines.

That repetition was not hypothetical. `health.router` was the only one of the thirty-one registered
without `DEFAULT_ERROR_RESPONSES`, so four operations documented a different error contract from the
other 245 — not by decision, but because it was first in the list and the line above it was the one
nobody copied. Applying the responses to `api_router` makes that class of defect unrepresentable:
there is no longer a per-router place to forget it.

**Order is preserved from the original registration and is load-bearing in one place.** The three
`pending_review` routers must stay `group` → `bulk` → `router`, because the last one owns
`/{pending_track_id}` and FastAPI matches in declaration order — registering it first would swallow
`/group/...` and `/bulk/...` as ids. ADR-0077 deleted an endpoint that had been unreachable for
exactly this reason (`GET /outputs/zones`, parsed as an output id), so it is worth stating rather
than trusting to the diff.
"""

from fastapi import APIRouter

from app.api.routes import (
    admin_artists,
    analysis,
    artwork,
    background,
    diagnostics,
    download,
    export_import,
    external_albums,
    favorites,
    health,
    lastfm,
    library,
    mixtapes,
    new_releases,
    organizer,
    outputs,
    pending_review,
    playback,
    playlists,
    profiles,
    proposed_changes,
    queue,
    s3_backup,
    smart_playlists,
    tracks,
    updates,
    videos,
)
from app.api.routes import (
    auth as auth_routes,
)
from app.api.routes import (
    settings as settings_routes,
)
from app.api.schemas.common import error_responses

# The error envelope every operation may return (ADR-0031's shape). Routes add their own statuses
# on top where one is real control flow; this is the floor, applied to the aggregate router below.
DEFAULT_ERROR_RESPONSES = error_responses(400, 401, 404, 422, 500)

api_router = APIRouter(responses=DEFAULT_ERROR_RESPONSES)

api_router.include_router(health.router)
api_router.include_router(auth_routes.router)
api_router.include_router(tracks.router)
api_router.include_router(library.router)
api_router.include_router(videos.router)
api_router.include_router(lastfm.router)
api_router.include_router(settings_routes.router)
api_router.include_router(smart_playlists.router)
api_router.include_router(playlists.router)
api_router.include_router(mixtapes.router)
api_router.include_router(profiles.router)
api_router.include_router(favorites.router)
api_router.include_router(organizer.router)
api_router.include_router(proposed_changes.router)
api_router.include_router(outputs.router)
api_router.include_router(artwork.router)
api_router.include_router(background.router)
api_router.include_router(diagnostics.router)
api_router.include_router(export_import.router)
api_router.include_router(s3_backup.router)
api_router.include_router(analysis.router)
api_router.include_router(download.router)
api_router.include_router(updates.router)
api_router.include_router(playback.router)
api_router.include_router(queue.router)
api_router.include_router(external_albums.router)
api_router.include_router(new_releases.router)
api_router.include_router(admin_artists.router)
# Order matters — see the module docstring.
api_router.include_router(pending_review.group_router)
api_router.include_router(pending_review.bulk_router)
api_router.include_router(pending_review.router)

__all__ = ["DEFAULT_ERROR_RESPONSES", "api_router"]
