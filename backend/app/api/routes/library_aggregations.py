"""Visualization aggregation endpoints (years, mood, letter-index)."""

import logging
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import String, func, select

from app.api.deps import DbSession
from app.db.models import Track, TrackAnalysis, TrackStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])


class YearCount(BaseModel):
    """Track count for a single year."""

    year: int
    track_count: int
    album_count: int
    artist_count: int


class YearDistributionResponse(BaseModel):
    """Year distribution for timeline visualization."""

    years: list[YearCount]
    total_with_year: int
    total_without_year: int
    min_year: int | None
    max_year: int | None


@router.get("/years", response_model=YearDistributionResponse)
async def get_year_distribution(db: DbSession) -> YearDistributionResponse:
    """Get track counts grouped by year for timeline visualization.

    Returns aggregated data suitable for large libraries.
    """
    # Query for year distribution
    year_query = (
        select(
            Track.year,
            func.count(Track.id).label("track_count"),
            func.count(func.distinct(Track.album)).label("album_count"),
            func.count(func.distinct(Track.artist)).label("artist_count"),
        )
        .where(
            Track.year.isnot(None),
            Track.status == TrackStatus.ACTIVE,
        )
        .group_by(Track.year)
        .order_by(Track.year)
    )

    result = await db.execute(year_query)
    rows = result.all()

    years = [
        YearCount(
            year=row.year,
            track_count=row.track_count,
            album_count=row.album_count,
            artist_count=row.artist_count,
        )
        for row in rows
    ]

    # Count tracks without year
    without_year = await db.scalar(
        select(func.count(Track.id)).where(
            Track.year.is_(None),
            Track.status == TrackStatus.ACTIVE,
        )
    ) or 0

    total_with = sum(y.track_count for y in years)
    min_year = years[0].year if years else None
    max_year = years[-1].year if years else None

    return YearDistributionResponse(
        years=years,
        total_with_year=total_with,
        total_without_year=without_year,
        min_year=min_year,
        max_year=max_year,
    )


class MoodCell(BaseModel):
    """A cell in the mood grid with track count."""

    energy_min: float
    energy_max: float
    valence_min: float
    valence_max: float
    track_count: int
    # Sample track IDs for this cell (for preview/playback)
    sample_track_ids: list[str]


class MoodDistributionResponse(BaseModel):
    """Mood distribution for 2D visualization."""

    cells: list[MoodCell]
    grid_size: int  # Number of cells per axis
    total_with_mood: int
    total_without_mood: int


@router.get("/mood-distribution", response_model=MoodDistributionResponse)
async def get_mood_distribution(
    db: DbSession,
    grid_size: int = 10,
) -> MoodDistributionResponse:
    """Get mood (energy x valence) distribution for heatmap visualization.

    Divides the 0-1 x 0-1 space into a grid and counts tracks per cell.
    Returns sample track IDs per cell for preview/playback.

    Uses SQL aggregation instead of loading all tracks into Python.
    """
    from sqlalchemy import Integer, cast, literal_column
    from sqlalchemy.dialects.postgresql import array_agg

    cell_size = 1.0 / grid_size

    # Use typed columns directly (one row per track via UniqueConstraint)
    energy_expr = TrackAnalysis.energy
    valence_expr = TrackAnalysis.valence

    # Bin into grid cells, clamped to [0, grid_size-1]
    energy_cell = func.least(
        cast(func.floor(energy_expr * grid_size), Integer),
        grid_size - 1,
    )
    valence_cell = func.least(
        cast(func.floor(valence_expr * grid_size), Integer),
        grid_size - 1,
    )

    # Aggregate: count and sample track IDs per cell
    grid_query = (
        select(
            energy_cell.label("e_cell"),
            valence_cell.label("v_cell"),
            func.count().label("cnt"),
            # Collect up to 5 sample track IDs per cell
            array_agg(cast(TrackAnalysis.track_id, String)).label("sample_ids"),
        )
        .select_from(TrackAnalysis)
        .join(Track, Track.id == TrackAnalysis.track_id)
        .where(
            Track.status == TrackStatus.ACTIVE,
            energy_expr.isnot(None),
            valence_expr.isnot(None),
        )
        .group_by(literal_column("e_cell"), literal_column("v_cell"))
    )

    result = await db.execute(grid_query)
    rows = result.all()

    # Count tracks with/without mood data
    total_with_mood = sum(row.cnt for row in rows)

    total_active = await db.scalar(
        select(func.count(Track.id)).where(Track.status == TrackStatus.ACTIVE)
    ) or 0
    total_without_mood = total_active - total_with_mood

    mood_cells = [
        MoodCell(
            energy_min=row.e_cell * cell_size,
            energy_max=(row.e_cell + 1) * cell_size,
            valence_min=row.v_cell * cell_size,
            valence_max=(row.v_cell + 1) * cell_size,
            track_count=row.cnt,
            sample_track_ids=row.sample_ids[:5] if row.sample_ids else [],
        )
        for row in rows
    ]

    return MoodDistributionResponse(
        cells=mood_cells,
        grid_size=grid_size,
        total_with_mood=total_with_mood,
        total_without_mood=total_without_mood,
    )


# ============================================================================
# Letter Index (for Alphabet Bar navigation)
# ============================================================================


class LetterIndexResponse(BaseModel):
    """Letter index for alphabet bar navigation."""

    letters: dict[str, int]  # {"A": 0, "B": 47, "C": 123, "#": 500}
    total: int


@router.get("/letter-index", response_model=LetterIndexResponse)
async def get_letter_index(
    db: DbSession,
    entity_type: Literal["tracks", "artists", "albums"] = "tracks",
    sort_field: str = "artist",  # tracks: artist/album/title, artists: name, albums: name/artist
    search: str | None = None,
    artist: str | None = None,
    album: str | None = None,
) -> LetterIndexResponse:
    """Get letter->index mapping for alphabet bar navigation.

    Returns the first occurrence index for each letter in the sorted list,
    allowing fast jumping to items starting with that letter.

    Non-alphabetic characters (numbers, symbols) map to '#'.

    Args:
        entity_type: What to index - 'tracks', 'artists', or 'albums'
        sort_field: Field to sort/index by
        search: Optional search filter
        artist: Filter by artist (for tracks/albums)
        album: Filter by album (for tracks only)
    """
    from sqlalchemy import case

    letters: dict[str, int] = {}
    total = 0

    if entity_type == "tracks":
        # Determine sort column based on sort_field
        if sort_field == "album":
            sort_col = func.coalesce(Track.album, "")
        elif sort_field == "title":
            sort_col = func.coalesce(Track.title, "")
        else:  # Default to artist
            sort_col = func.coalesce(Track.artist, "")

        # Build base query with filters
        base_filter = [Track.status == TrackStatus.ACTIVE]
        if search:
            search_lower = f"%{search.lower()}%"
            base_filter.append(
                (func.lower(Track.title).like(search_lower))
                | (func.lower(Track.artist).like(search_lower))
                | (func.lower(Track.album).like(search_lower))
            )
        if artist:
            base_filter.append(func.lower(Track.artist) == artist.lower())
        if album:
            base_filter.append(func.lower(Track.album) == album.lower())

        # Get total count
        count_query = select(func.count(Track.id)).where(*base_filter)
        total = await db.scalar(count_query) or 0

        # Extract first letter, normalize to uppercase, map non-alpha to '#'
        first_char = func.upper(func.substring(sort_col, 1, 1))
        letter_expr = case(
            (func.substring(first_char, 1, 1).op("~")("[A-Z]"), first_char),
            else_="#",
        )

        # Build subquery with row numbers
        row_num_query = (
            select(
                letter_expr.label("letter"),
                func.row_number()
                .over(order_by=[func.lower(sort_col), Track.album, Track.track_number])
                .label("row_num"),
            )
            .where(*base_filter)
            .subquery()
        )

        # Get first index for each letter
        letter_query = (
            select(
                row_num_query.c.letter,
                func.min(row_num_query.c.row_num).label("first_index"),
            )
            .group_by(row_num_query.c.letter)
            .order_by(row_num_query.c.letter)
        )

        result = await db.execute(letter_query)
        for row in result.all():
            # Convert to 0-based index
            letters[row.letter] = row.first_index - 1

    elif entity_type == "artists":
        # Sort by artist name
        sort_col = func.coalesce(func.max(Track.artist), "")  # Pick canonical display name
        artist_normalized = func.lower(Track.artist)

        # Build base filter
        base_filter = [
            Track.artist.isnot(None),
            Track.artist != "",
            Track.status == TrackStatus.ACTIVE,
        ]
        if search:
            base_filter.append(func.lower(Track.artist).contains(search.lower()))

        # Get total count
        count_query = (
            select(func.count(func.distinct(artist_normalized)))
            .select_from(Track)
            .where(*base_filter)
        )
        total = await db.scalar(count_query) or 0

        # Subquery to get distinct artists with row numbers
        artist_subquery = (
            select(
                func.max(Track.artist).label("name"),
                artist_normalized.label("artist_normalized"),
            )
            .where(*base_filter)
            .group_by(artist_normalized)
            .subquery()
        )

        # Add row numbers
        first_char = func.upper(func.substring(artist_subquery.c.name, 1, 1))
        letter_expr = case(
            (func.substring(first_char, 1, 1).op("~")("[A-Z]"), first_char),
            else_="#",
        )

        row_num_query = (
            select(
                letter_expr.label("letter"),
                func.row_number()
                .over(order_by=artist_subquery.c.artist_normalized)
                .label("row_num"),
            )
            .select_from(artist_subquery)
            .subquery()
        )

        # Get first index for each letter
        letter_query = (
            select(
                row_num_query.c.letter,
                func.min(row_num_query.c.row_num).label("first_index"),
            )
            .group_by(row_num_query.c.letter)
            .order_by(row_num_query.c.letter)
        )

        result = await db.execute(letter_query)
        for row in result.all():
            letters[row.letter] = row.first_index - 1

    elif entity_type == "albums":
        # Determine sort column
        album_artist_col = func.coalesce(func.nullif(Track.album_artist, ""), Track.artist)
        if sort_field == "artist":
            sort_col = album_artist_col
        else:  # Default to album name
            sort_col = func.coalesce(Track.album, "")

        # Build base filter
        base_filter = [
            Track.album.isnot(None),
            Track.album != "",
            Track.status == TrackStatus.ACTIVE,
        ]
        if search:
            search_lower = f"%{search.lower()}%"
            base_filter.append(
                (func.lower(Track.album).like(search_lower))
                | (func.lower(album_artist_col).like(search_lower))
            )
        if artist:
            base_filter.append(func.lower(album_artist_col) == artist.lower())

        # Subquery to get distinct albums
        album_artist_lower = func.lower(album_artist_col)
        album_lower = func.lower(Track.album)
        album_subquery = (
            select(
                func.max(Track.album).label("album_name"),
                func.max(album_artist_col).label("artist_name"),
                album_lower.label("album_normalized"),
                album_artist_lower.label("artist_normalized"),
            )
            .where(*base_filter)
            .group_by(album_artist_lower, album_lower)
            .subquery()
        )

        # Get total count
        count_query = select(func.count()).select_from(album_subquery)
        total = await db.scalar(count_query) or 0

        # Determine which column to use for letter extraction
        if sort_field == "artist":
            name_col = album_subquery.c.artist_name
            order_col = album_subquery.c.artist_normalized
        else:
            name_col = album_subquery.c.album_name
            order_col = album_subquery.c.album_normalized

        first_char = func.upper(func.substring(name_col, 1, 1))
        letter_expr = case(
            (func.substring(first_char, 1, 1).op("~")("[A-Z]"), first_char),
            else_="#",
        )

        row_num_query = (
            select(
                letter_expr.label("letter"),
                func.row_number().over(order_by=order_col).label("row_num"),
            )
            .select_from(album_subquery)
            .subquery()
        )

        # Get first index for each letter
        letter_query = (
            select(
                row_num_query.c.letter,
                func.min(row_num_query.c.row_num).label("first_index"),
            )
            .group_by(row_num_query.c.letter)
            .order_by(row_num_query.c.letter)
        )

        result = await db.execute(letter_query)
        for row in result.all():
            letters[row.letter] = row.first_index - 1

    return LetterIndexResponse(letters=letters, total=total)
