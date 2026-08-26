"""In-library suggestions for a playlist (ADR-0093).

Distinct from the sibling `recommendations.py`, and the difference is the whole point: that one asks
Last.fm and Bandcamp for music **not** in the library, which is "what should I go and get". These are
tracks already on disk, so `POST /playlists/{id}/tracks` can add them.
"""

from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import PlaylistNotFoundError
from app.api.schemas.suggestions import (
    SuggestedTrackResponse,
    SuggestedTracksResponse,
    SuggestionReasonResponse,
)
from app.api.schemas.tracks import TrackResponse
from app.db.models import Playlist, PlaylistTrack
from app.services.collection_suggestions import SEED_SAMPLE_CAP, suggest_for_collection

router = APIRouter()


@router.get("/{playlist_id}/suggested-tracks", response_model=SuggestedTracksResponse)
async def get_playlist_suggested_tracks(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    limit: int = Query(10, ge=1, le=50),
) -> SuggestedTracksResponse:
    """Tracks from your library that would fit this playlist and are not already in it.

    Each carries the playlist track that reached it, so the list explains itself.
    """
    playlist = await db.get(Playlist, playlist_id)
    if not playlist or playlist.profile_id != profile.id:
        raise PlaylistNotFoundError()

    # Ordered by position so the cap takes the head of the playlist rather than an arbitrary slice.
    member_ids = list(
        (
            await db.execute(
                select(PlaylistTrack.track_id)
                .where(PlaylistTrack.playlist_id == playlist_id)
                .order_by(PlaylistTrack.position)
            )
        )
        .scalars()
        .all()
    )

    suggestions = await suggest_for_collection(
        db,
        seed_track_ids=member_ids[:SEED_SAMPLE_CAP],
        # The **whole** playlist, not the capped seed — ADR-0093 point 4. A playlist longer than the
        # cap would otherwise be offered tracks from its own tail.
        exclude_track_ids=set(member_ids),
        profile_id=profile.id,
        limit=limit,
    )

    return SuggestedTracksResponse(
        suggestions=[
            SuggestedTrackResponse(
                track=TrackResponse.model_validate(s.track, from_attributes=True),
                because_of=SuggestionReasonResponse(
                    track_id=s.because_of.id,
                    title=s.because_of.title,
                    artist=s.because_of.artist,
                ),
                similarity=s.similarity,
                votes=s.votes,
            )
            for s in suggestions
        ],
        seed_track_count=len(member_ids),
    )
