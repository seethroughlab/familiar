"""Track metadata CRUD endpoints: update, get, bulk edit, common values, lookup."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.api.exceptions import TrackNotFoundError
from app.db.models import Track
from app.services import metadata_overrides

from . import TrackFeaturesResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class TrackMetadataUpdateRequest(BaseModel):
    """Request to update track metadata.

    All fields are optional - only provided fields are updated.
    """

    # Core metadata
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    year: int | None = None
    genre: str | None = None

    # Extended metadata
    composer: str | None = None
    conductor: str | None = None
    lyricist: str | None = None
    grouping: str | None = None
    comment: str | None = None

    # Sort fields
    sort_artist: str | None = None
    sort_album: str | None = None
    sort_title: str | None = None

    # Lyrics
    lyrics: str | None = None

    # User overrides for analysis values (bpm, key, etc.)
    user_overrides: dict[str, Any] | None = None

    @field_validator(
        "title",
        "artist",
        "album",
        "album_artist",
        "genre",
        "composer",
        "conductor",
        "lyricist",
        "grouping",
        "comment",
        "sort_artist",
        "sort_album",
        "sort_title",
        "lyrics",
        mode="before",
    )
    @classmethod
    def _blank_means_absent(cls, value: Any) -> Any:
        """A blank string clears the tag rather than storing an empty one.

        Two reasons, and the second is why this lives on the server.

        An empty genre is not a genre. Stored as ``""`` it sorts and groups apart from every track
        that simply has none, so "no genre" quietly becomes two different things depending on
        whether somebody once typed in the box and changed their mind.

        And it is the only way the Swift client can clear anything at all.
        ``Components.Schemas.TrackMetadataUpdateRequest.genre`` is a plain ``String?`` with
        synthesised ``Codable``, which omits a nil rather than writing ``null`` — so setting the
        property to nil was indistinguishable from never touching it, and clearing a tag on the Mac
        reported success and did nothing. The client now sends ``""`` and means it. See
        ``MetadataClearingTests`` in familiar-apple, which asserts that encoding directly.

        Numeric fields are deliberately not covered: ``year`` and the track and disc numbers are
        ``int | None``, an empty string is not a number, and there is no blank to interpret.
        """
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


class TrackMetadataResponse(BaseModel):
    """Extended track response with all metadata fields."""

    id: UUID
    file_path: str

    # Core metadata
    title: str | None
    artist: str | None
    album: str | None
    album_artist: str | None
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str | None

    # Extended metadata
    composer: str | None = None
    conductor: str | None = None
    lyricist: str | None = None
    grouping: str | None = None
    comment: str | None = None

    # Sort fields
    sort_artist: str | None = None
    sort_album: str | None = None
    sort_title: str | None = None

    # Lyrics
    lyrics: str | None = None

    # User overrides
    user_overrides: dict[str, Any] = {}

    # Audio info
    duration_seconds: float | None
    format: str | None

    # Analysis
    features: TrackFeaturesResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class BulkMetadataUpdateRequest(BaseModel):
    """Request to update metadata for multiple tracks."""

    track_ids: list[UUID]
    metadata: TrackMetadataUpdateRequest


class BulkEditErrorResponse(BaseModel):
    """Error for a single track in bulk edit."""

    track_id: str
    file_path: str
    error: str


class BulkEditResultResponse(BaseModel):
    """Result of bulk edit operation."""

    total: int
    successful: int
    failed: int
    errors: list[BulkEditErrorResponse]
    fields_updated: list[str]


class CommonValuesRequest(BaseModel):
    """Request to get common values across tracks."""

    track_ids: list[UUID]


class CommonValuesResponse(BaseModel):
    """Common values across multiple tracks.

    Fields with identical values across all tracks have that value.
    Fields with different values are None (representing "mixed").
    """

    # Core metadata
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    year: int | None = None
    genre: str | None = None

    # Extended metadata
    composer: str | None = None
    conductor: str | None = None
    lyricist: str | None = None
    grouping: str | None = None
    comment: str | None = None

    # Sort fields
    sort_artist: str | None = None
    sort_album: str | None = None
    sort_title: str | None = None

    # Lyrics
    lyrics: str | None = None

    # Track count for UI
    track_count: int = 0


class MetadataLookupRequest(BaseModel):
    """Request to look up track metadata from external sources."""

    title: str
    artist: str
    album: str | None = None


class MetadataCandidateResponse(BaseModel):
    """A candidate metadata match."""

    source: str
    source_id: str
    confidence: float
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    year: int | None = None
    track_number: int | None = None
    genre: str | None = None
    artwork_url: str | None = None


@router.patch("/{track_id}/metadata", response_model=TrackMetadataResponse)
async def update_track_metadata(
    db: DbSession,
    track_id: UUID,
    request: TrackMetadataUpdateRequest,
) -> TrackMetadataResponse:
    """Update track metadata in the database.

    Only provided fields are updated.

    Returns the updated track with all metadata fields.
    """

    # Get track (only ACTIVE tracks can be edited via this endpoint)
    query = select(Track).options(selectinload(Track.analyses)).where(Track.id == track_id, Track.active_filter())
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    # Update only provided fields
    update_data = request.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        if hasattr(track, field):
            setattr(track, field, value)

    # Remember that these were chosen rather than read off the file, so a rescan cannot undo them.
    # Assigned rather than mutated in place: SQLAlchemy does not notice in-place changes to JSONB.
    track.metadata_overrides = metadata_overrides.record(track.metadata_overrides, update_data)

    # Commit database changes
    await db.commit()
    await db.refresh(track)

    # Prepare response
    response = TrackMetadataResponse.model_validate(track)

    # Get latest analysis features
    if track.analyses:
        latest = track.analyses[0]
        if latest.bpm is not None:
            # Merge user overrides with analysis features
            features_data: dict[str, Any] = {
                "bpm": latest.bpm,
                "key": latest.key,
                "energy": latest.energy,
                "danceability": latest.danceability,
                "valence": latest.valence,
                "acousticness": latest.acousticness,
                "instrumentalness": latest.instrumentalness,
                "speechiness": latest.speechiness,
                "loudness_lufs": latest.loudness_lufs,
                "track_peak": latest.track_peak,
                "replaygain_track_gain": latest.replaygain_track_gain,
            }
            # Apply user overrides
            if track.user_overrides:
                for key, val in track.user_overrides.items():
                    if key in features_data:
                        features_data[key] = val
            response.features = TrackFeaturesResponse(**features_data)

    return response


@router.get("/{track_id}/metadata", response_model=TrackMetadataResponse)
async def get_track_metadata(
    db: DbSession,
    track_id: UUID,
) -> TrackMetadataResponse:
    """Get full track metadata including extended fields.

    Returns all metadata fields including composer, conductor, lyrics, etc.
    User overrides are merged with analysis features.
    """
    query = select(Track).options(selectinload(Track.analyses)).where(Track.id == track_id, Track.active_filter())
    result = await db.execute(query)
    track = result.scalar_one_or_none()

    if not track:
        raise TrackNotFoundError()

    response = TrackMetadataResponse.model_validate(track)

    # Get latest analysis features with user overrides applied
    if track.analyses:
        latest = track.analyses[0]
        if latest.bpm is not None:
            features_data: dict[str, Any] = {
                "bpm": latest.bpm,
                "key": latest.key,
                "energy": latest.energy,
                "danceability": latest.danceability,
                "valence": latest.valence,
                "acousticness": latest.acousticness,
                "instrumentalness": latest.instrumentalness,
                "speechiness": latest.speechiness,
                "loudness_lufs": latest.loudness_lufs,
                "track_peak": latest.track_peak,
                "replaygain_track_gain": latest.replaygain_track_gain,
            }
            # Apply user overrides
            if track.user_overrides:
                for key, val in track.user_overrides.items():
                    if key in features_data:
                        features_data[key] = val
            response.features = TrackFeaturesResponse(**features_data)

    return response


@router.post("/bulk/metadata", response_model=BulkEditResultResponse)
async def bulk_update_metadata(
    db: DbSession,
    request: BulkMetadataUpdateRequest,
) -> BulkEditResultResponse:
    """Update metadata for multiple tracks at once.

    Only provided (non-None) fields in metadata are applied to all tracks.

    Returns summary with success/failure counts and any errors.
    """
    from app.services.bulk_editor import BulkEditorService

    service = BulkEditorService(db)

    # Extract metadata dict
    metadata_dict = request.metadata.model_dump(exclude_unset=True)

    result = await service.apply_to_tracks(
        track_ids=request.track_ids,
        metadata=metadata_dict,
    )

    return BulkEditResultResponse(
        total=result.total,
        successful=result.successful,
        failed=result.failed,
        errors=[
            BulkEditErrorResponse(
                track_id=e.track_id, file_path=e.file_path, error=e.error
            )
            for e in result.errors
        ],
        fields_updated=result.fields_updated,
    )


@router.post("/bulk/common-values", response_model=CommonValuesResponse)
async def get_common_values(
    db: DbSession,
    request: CommonValuesRequest,
) -> CommonValuesResponse:
    """Get common field values across multiple tracks.

    Used to pre-fill the bulk edit form. Fields with different values
    across the selected tracks are returned as None (indicating "mixed").
    """
    from app.services.bulk_editor import BulkEditorService

    service = BulkEditorService(db)
    common = await service.get_common_values(request.track_ids)

    return CommonValuesResponse(
        **common,
        track_count=len(request.track_ids),
    )


@router.post("/lookup/metadata", response_model=list[MetadataCandidateResponse])
async def lookup_metadata(
    request: MetadataLookupRequest,
) -> list[MetadataCandidateResponse]:
    """Look up track metadata from MusicBrainz.

    Returns a list of candidate matches sorted by confidence.
    Use this to find correct metadata for tracks with incomplete or wrong info.
    """
    from app.services.metadata.lookup import MetadataLookupService

    service = MetadataLookupService()
    candidates = await service.lookup_track(
        title=request.title,
        artist=request.artist,
        album=request.album,
        limit=5,
    )

    return [
        MetadataCandidateResponse(
            source=c.source,
            source_id=c.source_id,
            confidence=c.confidence,
            title=c.metadata.get("title"),
            artist=c.metadata.get("artist"),
            album=c.metadata.get("album"),
            album_artist=c.metadata.get("album_artist"),
            year=c.metadata.get("year"),
            track_number=c.metadata.get("track_number"),
            genre=c.metadata.get("genre"),
            artwork_url=c.artwork_url,
        )
        for c in candidates
    ]
