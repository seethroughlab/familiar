"""Seeded playlist generation (ADR-0048).

`POST /api/v1/playlists/generate` takes a structured seed and returns a saved playlist. It is what
the four "Make a playlist" context-menu items call, and what the `generate_playlist` MCP tool calls,
so the app and an MCP host share one implementation and cannot drift (point 8).

**No English sentence is constructed anywhere.** That is what makes the button independent of
whether any language model exists — which matters, because after ADR-0043 point 5 this server has
none.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import NotFoundError, ValidationError
from app.api.schemas.common import error_responses
from app.db.models import Playlist, PlaylistTrack
from app.services.playlist_generation import (
    generate_seeded_playlist,
    resolve_seed,
)

router = APIRouter()


class GeneratePlaylistRequest(BaseModel):
    """A closed, structured seed — ADR-0048 point 2.

    **Free text is deliberately not accepted.** A sentence would re-introduce interpretation, and
    interpretation is the one thing that genuinely needed a model. Every caller of this endpoint has
    already been told the seed by a right-click.
    """

    track_id: UUID | None = None
    artist: str | None = None
    album: str | None = None
    track_ids: list[UUID] | None = None

    limit: int = Field(default=25, ge=5, le=100)
    max_per_artist: int = Field(default=2, ge=1, le=10)
    max_per_album: int = Field(default=2, ge=1, le=10)
    include_seed: bool = False
    #: Overrides the deterministic name. The clients do not send it; an MCP host might.
    name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def exactly_one_seed(self) -> GeneratePlaylistRequest:
        # `album` may travel with `artist` to disambiguate — "Greatest Hits" is not one album — so
        # that pair counts as a single seed rather than two.
        shapes = [
            self.track_id is not None,
            bool(self.track_ids),
            self.album is not None,
            self.artist is not None and self.album is None,
        ]
        if sum(shapes) != 1:
            raise ValueError(
                "Provide exactly one seed: track_id, album (optionally with artist), "
                "artist, or track_ids."
            )
        return self


class GeneratePlaylistResponse(BaseModel):
    playlist_id: UUID
    name: str
    track_count: int
    seed_track_ids: list[UUID]
    #: How many candidates were scored. A small number here is the usual reason a playlist
    #: disappoints, and it is invisible from the track list alone.
    pool_size: int


@router.post(
    "/generate",
    operation_id="playlists_generate",
    response_model=GeneratePlaylistResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(404, 422),
)
async def generate_playlist(
    request: GeneratePlaylistRequest,
    db: DbSession,
    profile: RequiredProfile,
) -> GeneratePlaylistResponse:
    """Generate and save a playlist from a structured seed.

    Returns a **saved** playlist, not a preview (point 6): it is reached from a menu item that said
    "Make a playlist", and a confirmation step would make the button a lie. It is marked
    `is_auto_generated` so it sorts and filters with the others and is one action to delete.
    """
    seed = await resolve_seed(
        db,
        track_id=request.track_id,
        artist=request.artist,
        album=request.album,
        track_ids=request.track_ids,
    )
    if seed is None:
        # A 404 rather than an empty playlist: "make a playlist from an album that is not in your
        # library" has no sensible empty answer, and saving one would leave the listener with a
        # playlist they have to work out how to interpret.
        raise NotFoundError("No tracks matched that seed")

    result = await generate_seeded_playlist(
        db,
        seed,
        limit=request.limit,
        max_per_artist=request.max_per_artist,
        max_per_album=request.max_per_album,
        include_seed=request.include_seed,
        profile_id=profile.id,
    )

    if not result.track_ids:
        # Nothing cleared `MIN_SCORE`. Saving an empty playlist would be worse than saying so —
        # the listener would find it in their sidebar and have no idea why it was empty.
        raise ValidationError(
            "Nothing in the library was close enough to that seed to make a playlist from."
        )

    playlist = Playlist(
        profile_id=profile.id,
        name=request.name or result.name,
        description=None,
        is_auto_generated=True,
        # Deliberately not a prompt: there was no prompt. Recording the seed rather than a sentence
        # is what makes this reproducible.
        generation_prompt=f"seed:{seed.kind}:{seed.label}",
    )
    db.add(playlist)
    await db.flush()

    for position, track_id in enumerate(result.track_ids):
        db.add(PlaylistTrack(playlist_id=playlist.id, track_id=track_id, position=position))

    await db.commit()

    return GeneratePlaylistResponse(
        playlist_id=playlist.id,
        name=playlist.name,
        track_count=len(result.track_ids),
        seed_track_ids=result.seed_track_ids,
        pool_size=result.pool_size,
    )
