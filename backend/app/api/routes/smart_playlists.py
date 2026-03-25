"""Smart playlist API endpoints."""

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, UploadFile, status
from pydantic import BaseModel, Field

from sqlalchemy import select

from app.api.deps import DbSession, RequiredProfile
from app.api.exceptions import NotFoundError, ValidationError, sanitize_error_for_client
from app.api.schemas.tracks import TrackResponse
from app.db.models import ProfilePlayHistory
from app.services.smart_playlists import SmartPlaylistService

router = APIRouter(prefix="/smart-playlists", tags=["smart-playlists"])


class RuleSchema(BaseModel):
    """A single rule for matching tracks."""

    field: str = Field(..., description="Field to match (e.g., 'genre', 'bpm', 'energy')")
    operator: str = Field(..., description="Comparison operator")
    value: Any | None = Field(None, description="Value to compare against")


class SmartPlaylistCreate(BaseModel):
    """Request to create a smart playlist."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    rules: list[RuleSchema] = Field(default_factory=list)
    match_mode: str = Field(default="all", pattern="^(all|any)$")
    order_by: str = Field(default="title")
    order_direction: str = Field(default="asc", pattern="^(asc|desc)$")
    max_tracks: int | None = Field(default=None, ge=1, le=10000)


class SmartPlaylistUpdate(BaseModel):
    """Request to update a smart playlist."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    rules: list[RuleSchema] | None = None
    match_mode: str | None = Field(None, pattern="^(all|any)$")
    order_by: str | None = None
    order_direction: str | None = Field(None, pattern="^(asc|desc)$")
    max_tracks: int | None = Field(None, ge=1, le=10000)
    auto_download: bool | None = None


class SmartPlaylistResponse(BaseModel):
    """Smart playlist response."""

    id: str
    name: str
    description: str | None
    rules: list[dict[str, Any]]
    match_mode: str
    order_by: str
    order_direction: str
    max_tracks: int | None
    cached_track_count: int
    last_refreshed_at: str | None
    auto_download: bool = False
    created_at: str
    updated_at: str


class SmartPlaylistTracksResponse(BaseModel):
    """Response with smart playlist tracks."""

    playlist: SmartPlaylistResponse
    tracks: list[TrackResponse]
    total: int


def playlist_to_response(playlist: Any) -> SmartPlaylistResponse:
    """Convert SmartPlaylist model to response."""
    return SmartPlaylistResponse(
        id=str(playlist.id),
        name=playlist.name,
        description=playlist.description,
        rules=playlist.rules,
        match_mode=playlist.match_mode,
        order_by=playlist.order_by,
        order_direction=playlist.order_direction,
        max_tracks=playlist.max_tracks,
        cached_track_count=playlist.cached_track_count,
        last_refreshed_at=playlist.last_refreshed_at.isoformat() if playlist.last_refreshed_at else None,
        auto_download=playlist.auto_download,
        created_at=playlist.created_at.isoformat(),
        updated_at=playlist.updated_at.isoformat(),
    )


@router.get("", response_model=list[SmartPlaylistResponse])
async def list_smart_playlists(
    db: DbSession,
    profile: RequiredProfile,
) -> list[SmartPlaylistResponse]:
    """List all smart playlists for the current profile."""
    service = SmartPlaylistService(db)
    playlists = await service.get_all_for_profile(profile.id)
    return [playlist_to_response(p) for p in playlists]


@router.post("", response_model=SmartPlaylistResponse, status_code=status.HTTP_201_CREATED)
async def create_smart_playlist(
    request: SmartPlaylistCreate,
    db: DbSession,
    profile: RequiredProfile,
) -> SmartPlaylistResponse:
    """Create a new smart playlist."""
    service = SmartPlaylistService(db)

    try:
        playlist = await service.create(
            profile_id=profile.id,
            name=request.name,
            description=request.description,
            rules=[r.model_dump() for r in request.rules],
            match_mode=request.match_mode,
            order_by=request.order_by,
            order_direction=request.order_direction,
            max_tracks=request.max_tracks,
        )
    except ValueError as e:
        raise ValidationError(sanitize_error_for_client(e, "Invalid smart playlist configuration"))

    return playlist_to_response(playlist)


@router.get("/{playlist_id}", response_model=SmartPlaylistResponse)
async def get_smart_playlist(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> SmartPlaylistResponse:
    """Get a smart playlist by ID."""
    service = SmartPlaylistService(db)
    playlist = await service.get_by_id(playlist_id, profile.id)

    if not playlist:
        raise NotFoundError("Smart playlist not found")

    return playlist_to_response(playlist)


@router.put("/{playlist_id}", response_model=SmartPlaylistResponse)
async def update_smart_playlist(
    playlist_id: UUID,
    request: SmartPlaylistUpdate,
    db: DbSession,
    profile: RequiredProfile,
) -> SmartPlaylistResponse:
    """Update a smart playlist."""
    service = SmartPlaylistService(db)
    playlist = await service.get_by_id(playlist_id, profile.id)

    if not playlist:
        raise NotFoundError("Smart playlist not found")

    update_data = request.model_dump(exclude_unset=True)
    if "rules" in update_data and update_data["rules"] is not None:
        update_data["rules"] = [r if isinstance(r, dict) else r.model_dump() for r in update_data["rules"]]

    try:
        playlist = await service.update(playlist, **update_data)
    except ValueError as e:
        raise ValidationError(sanitize_error_for_client(e, "Invalid smart playlist configuration"))

    return playlist_to_response(playlist)


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_smart_playlist(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> None:
    """Delete a smart playlist."""
    service = SmartPlaylistService(db)
    playlist = await service.get_by_id(playlist_id, profile.id)

    if not playlist:
        raise NotFoundError("Smart playlist not found")

    await service.delete(playlist)


@router.get("/{playlist_id}/tracks", response_model=SmartPlaylistTracksResponse)
async def get_smart_playlist_tracks(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
    limit: int = 100,
    offset: int = 0,
) -> SmartPlaylistTracksResponse:
    """Get tracks matching a smart playlist's rules."""
    service = SmartPlaylistService(db)
    playlist = await service.get_by_id(playlist_id, profile.id)

    if not playlist:
        raise NotFoundError("Smart playlist not found")

    tracks = await service.get_tracks(playlist, limit=limit, offset=offset)
    total = await service.get_track_count(playlist)

    # Fetch play history for all tracks
    track_ids = [t.id for t in tracks]
    play_history_map = {}
    if track_ids:
        ph_result = await db.execute(
            select(ProfilePlayHistory).where(
                ProfilePlayHistory.profile_id == profile.id,
                ProfilePlayHistory.track_id.in_(track_ids),
            )
        )
        play_history_map = {ph.track_id: ph for ph in ph_result.scalars().all()}

    track_responses = []
    for t in tracks:
        resp = TrackResponse.model_validate(t)
        if t.id in play_history_map:
            ph = play_history_map[t.id]
            resp.last_played_at = ph.last_played_at
            resp.play_count = ph.play_count
        track_responses.append(resp)

    return SmartPlaylistTracksResponse(
        playlist=playlist_to_response(playlist),
        tracks=track_responses,
        total=total,
    )


@router.post("/{playlist_id}/refresh", response_model=SmartPlaylistResponse)
async def refresh_smart_playlist(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> SmartPlaylistResponse:
    """Refresh a smart playlist's cached track count."""
    service = SmartPlaylistService(db)
    playlist = await service.get_by_id(playlist_id, profile.id)

    if not playlist:
        raise NotFoundError("Smart playlist not found")

    await service.refresh_playlist(playlist)
    return playlist_to_response(playlist)


class ConvertToStaticResponse(BaseModel):
    """Response for converting a smart playlist to a static playlist."""

    playlist_id: str
    name: str
    track_count: int


@router.post("/{playlist_id}/convert-to-static", response_model=ConvertToStaticResponse)
async def convert_to_static(
    playlist_id: UUID,
    db: DbSession,
    profile: RequiredProfile,
) -> ConvertToStaticResponse:
    """Convert a smart playlist to a static playlist.

    Resolves the current matching tracks and creates a new static Playlist.
    The smart playlist is NOT deleted.
    """
    service = SmartPlaylistService(db)
    playlist = await service.get_by_id(playlist_id, profile.id)

    if not playlist:
        raise NotFoundError("Smart playlist not found")

    static_id, static_name, track_count = await service.convert_to_static(playlist, profile.id)

    return ConvertToStaticResponse(
        playlist_id=str(static_id),
        name=static_name,
        track_count=track_count,
    )


@router.get("/fields/available")
async def get_available_fields() -> dict[str, Any]:
    """Get list of available fields and operators for building rules."""
    return {
        "track_fields": [
            {"name": "title", "type": "string", "description": "Track title"},
            {"name": "artist", "type": "string", "description": "Artist name"},
            {"name": "album", "type": "string", "description": "Album name"},
            {"name": "album_artist", "type": "string", "description": "Album artist"},
            {"name": "genre", "type": "string", "description": "Genre"},
            {"name": "year", "type": "number", "description": "Release year"},
            {"name": "duration_seconds", "type": "number", "description": "Track duration in seconds"},
            {"name": "format", "type": "string", "description": "Audio format (mp3, flac, etc.)"},
            {"name": "created_at", "type": "date", "description": "Date added to library"},
            {"name": "composer", "type": "string", "description": "Composer"},
            {"name": "comment", "type": "string", "description": "Comment/notes"},
            {"name": "grouping", "type": "string", "description": "Grouping"},
            {"name": "file_path", "type": "string", "description": "File path"},
        ],
        "analysis_fields": [
            {"name": "bpm", "type": "number", "description": "Beats per minute", "range": [60, 200]},
            {"name": "key", "type": "string", "description": "Musical key (e.g., 'C', 'Am')"},
            {"name": "energy", "type": "number", "description": "Energy level", "range": [0, 1]},
            {"name": "valence", "type": "number", "description": "Musical positivity", "range": [0, 1]},
            {"name": "danceability", "type": "number", "description": "How danceable", "range": [0, 1]},
            {"name": "acousticness", "type": "number", "description": "Acoustic vs electronic", "range": [0, 1]},
            {"name": "instrumentalness", "type": "number", "description": "Instrumental vs vocal", "range": [0, 1]},
            {"name": "speechiness", "type": "number", "description": "Presence of spoken words", "range": [0, 1]},
        ],
        "play_history_fields": [
            {"name": "last_played_at", "type": "date", "description": "Last played"},
            {"name": "play_count", "type": "number", "description": "Play count"},
            {"name": "total_play_seconds", "type": "number", "description": "Total play time (seconds)"},
            {"name": "never_played", "type": "boolean", "description": "Never played"},
        ],
        "operators": {
            "string": ["equals", "not_equals", "contains", "not_contains", "starts_with", "ends_with", "is_empty", "is_not_empty"],
            "number": ["equals", "not_equals", "greater_than", "less_than", "greater_or_equal", "less_or_equal", "between"],
            "date": [
                "within_days", "not_within_days",  # Legacy (keep for compatibility)
                "after", "before", "on",            # Absolute date operators
                "in_the_last", "not_in_the_last",   # Relative date operators
                "is_empty", "is_not_empty",
            ],
            "boolean": ["equals"],
            "list": ["in", "not_in"],
        },
        "date_keywords": ["today", "yesterday", "this_week", "last_week", "this_month", "last_month", "this_year", "last_year"],
        "relative_units": ["days", "weeks", "months", "years"],
    }


class PlaylistImportResult(BaseModel):
    """Result of importing a .familiar playlist file."""

    playlist_id: str
    playlist_name: str
    total_tracks: int
    matched_tracks: int
    unmatched_tracks: int


@router.post("/import", response_model=PlaylistImportResult)
async def import_playlist(
    db: DbSession,
    profile: RequiredProfile,
    file: UploadFile = File(...),
):
    """Import a .familiar playlist file.

    The file should be a JSON file with the format:
    {
        "format": "familiar-playlist",
        "version": 1,
        "playlist": {
            "name": "...",
            "description": "...",
            "type": "smart" | "static",
            "rules": [...],  // for smart playlists
            "match_mode": "all" | "any",
            "tracks": [...]
        }
    }

    Tracks are matched to the local library by title and artist.
    """
    # Read and parse the file
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise ValidationError("Invalid JSON", detail=str(e))

    # Validate format
    if data.get("format") != "familiar-playlist":
        raise ValidationError("Invalid file format. Expected a .familiar playlist file.")

    service = SmartPlaylistService(db)
    playlist_id, playlist_name, matched_count, total_tracks = await service.import_playlist_file(
        profile_id=profile.id, data=data,
    )

    return PlaylistImportResult(
        playlist_id=str(playlist_id),
        playlist_name=playlist_name,
        total_tracks=total_tracks,
        matched_tracks=matched_count,
        unmatched_tracks=total_tracks - matched_count,
    )
