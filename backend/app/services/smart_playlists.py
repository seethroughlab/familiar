"""Smart playlist service for rule-based auto-updating playlists."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProfilePlayHistory, SmartPlaylist, Track, TrackAnalysis
from app.utils.time import utcnow

# Fields that exist directly on the Track model
TRACK_FIELDS = {
    "title", "artist", "album", "album_artist", "genre", "year",
    "track_number", "disc_number", "duration_seconds", "format",
    "created_at", "album_type",
    # Additional metadata fields
    "composer", "comment", "grouping", "file_path",
}

# Date/timestamp fields that need special handling
DATE_FIELDS = {"created_at", "last_played_at"}

# String fields that support ILIKE operations
STRING_FIELDS = {
    "title", "artist", "album", "album_artist", "genre", "format", "album_type",
    "composer", "comment", "grouping", "file_path",
}

# Numeric fields
NUMERIC_FIELDS = {"year", "track_number", "disc_number", "duration_seconds", "play_count", "total_play_seconds"}

# Fields from ProfilePlayHistory (profile-scoped play history)
PLAY_HISTORY_FIELDS = {
    "last_played_at",      # datetime - when track was last played
    "play_count",          # int - number of times played
    "total_play_seconds",  # float - cumulative play time
    "never_played",        # boolean - tracks with no play history
}

# Boolean fields
BOOLEAN_FIELDS = {"never_played"}

# Fields that exist as typed columns on TrackAnalysis
ANALYSIS_FIELDS = {
    "bpm", "key", "energy", "valence", "danceability",
    "acousticness", "instrumentalness", "speechiness",
    "loudness_lufs", "dynamic_range_db", "swing_ratio",
    "syncopation", "brightness", "harmonic_complexity",
    "note_density", "section_count", "avg_section_length",
}

# Valid operators
OPERATORS = {
    "equals", "not_equals", "contains", "not_contains",
    "starts_with", "ends_with",
    "greater_than", "less_than", "greater_or_equal", "less_or_equal",
    "between", "in", "not_in",
    "is_empty", "is_not_empty",
    "within_days",  # For date fields (legacy)
    "not_within_days",  # For date fields - not played in last N days (legacy)
    # New date operators
    "after",           # date > value (supports keywords: today, yesterday, this_week, etc.)
    "before",          # date < value
    "on",              # date == value (same day)
    "in_the_last",     # relative: value = {"amount": 3, "unit": "weeks"}
    "not_in_the_last", # not within relative time
}

# Date keywords for after/before/on operators
DATE_KEYWORDS = {
    "today": lambda: utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
    "yesterday": lambda: utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1),
    "this_week": lambda: utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=utcnow().weekday()),
    "last_week": lambda: utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=utcnow().weekday() + 7),
    "this_month": lambda: utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    "last_month": lambda: (utcnow().replace(day=1) - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    "this_year": lambda: utcnow().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
    "last_year": lambda: utcnow().replace(year=utcnow().year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
}


def resolve_date_value(value: Any) -> datetime | None:
    """Resolve date value from keyword, ISO string, or datetime."""
    if isinstance(value, str):
        # Check for keyword
        if value in DATE_KEYWORDS:
            return DATE_KEYWORDS[value]()
        # Try parsing as ISO date
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def resolve_relative_date(value: Any) -> datetime | None:
    """Resolve relative date like {"amount": 3, "unit": "weeks"}."""
    if not isinstance(value, dict):
        return None
    amount = value.get("amount", 0)
    unit = value.get("unit", "days")

    try:
        amount = int(amount)
    except (ValueError, TypeError):
        return None

    if unit == "days":
        return utcnow() - timedelta(days=amount)
    elif unit == "weeks":
        return utcnow() - timedelta(weeks=amount)
    elif unit == "months":
        return utcnow() - timedelta(days=amount * 30)  # Approximate
    elif unit == "years":
        return utcnow() - timedelta(days=amount * 365)  # Approximate
    return None


class SmartPlaylistService:
    """Service for managing and executing smart playlists."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        profile_id: UUID,
        name: str,
        rules: list[dict[str, Any]],
        description: str | None = None,
        match_mode: str = "all",
        order_by: str = "title",
        order_direction: str = "asc",
        max_tracks: int | None = None,
    ) -> SmartPlaylist:
        """Create a new smart playlist."""
        # Validate rules
        self._validate_rules(rules)

        playlist = SmartPlaylist(
            profile_id=profile_id,
            name=name,
            description=description,
            rules=rules,
            match_mode=match_mode,
            order_by=order_by,
            order_direction=order_direction,
            max_tracks=max_tracks,
        )

        self.db.add(playlist)
        await self.db.commit()
        await self.db.refresh(playlist)

        # Refresh to get initial count
        await self.refresh_playlist(playlist)

        return playlist

    async def update(
        self,
        playlist: SmartPlaylist,
        **kwargs: Any,
    ) -> SmartPlaylist:
        """Update a smart playlist."""
        if "rules" in kwargs:
            self._validate_rules(kwargs["rules"])

        for key, value in kwargs.items():
            if hasattr(playlist, key):
                setattr(playlist, key, value)

        await self.db.commit()
        await self.db.refresh(playlist)

        # Refresh to update count
        await self.refresh_playlist(playlist)

        return playlist

    async def delete(self, playlist: SmartPlaylist) -> None:
        """Delete a smart playlist."""
        await self.db.delete(playlist)
        await self.db.commit()

    async def get_by_id(self, playlist_id: UUID, profile_id: UUID) -> SmartPlaylist | None:
        """Get a smart playlist by ID."""
        result = await self.db.execute(
            select(SmartPlaylist).where(
                SmartPlaylist.id == playlist_id,
                SmartPlaylist.profile_id == profile_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_all_for_profile(self, profile_id: UUID) -> list[SmartPlaylist]:
        """Get all smart playlists for a profile."""
        result = await self.db.execute(
            select(SmartPlaylist)
            .where(SmartPlaylist.profile_id == profile_id)
            .order_by(SmartPlaylist.name)
        )
        return list(result.scalars().all())

    async def get_tracks(
        self,
        playlist: SmartPlaylist,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Track]:
        """Get tracks matching the smart playlist rules."""
        query = self._build_query(playlist, playlist.profile_id)

        # Apply ordering
        order_column = self._get_order_column(playlist.order_by)
        if playlist.order_direction == "desc":
            query = query.order_by(order_column.desc())
        else:
            query = query.order_by(order_column.asc())

        # Apply limits
        effective_limit = limit
        if playlist.max_tracks:
            effective_limit = min(limit or playlist.max_tracks, playlist.max_tracks)

        if effective_limit:
            query = query.limit(effective_limit)
        if offset:
            query = query.offset(offset)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_track_count(self, playlist: SmartPlaylist) -> int:
        """Get the count of tracks matching the rules."""
        query = self._build_query(playlist, playlist.profile_id)
        count_query = select(func.count()).select_from(query.subquery())
        result = await self.db.execute(count_query)
        return result.scalar() or 0

    async def refresh_playlist(self, playlist: SmartPlaylist) -> int:
        """Refresh the cached track count."""
        count = await self.get_track_count(playlist)
        playlist.cached_track_count = count
        playlist.last_refreshed_at = utcnow()
        await self.db.commit()
        await self.db.refresh(playlist)
        return count

    def _validate_rules(self, rules: list[dict[str, Any]]) -> None:
        """Validate rule structure."""
        all_valid_fields = TRACK_FIELDS | ANALYSIS_FIELDS | PLAY_HISTORY_FIELDS | {"mood_tag"}
        string_operators = {"contains", "not_contains", "starts_with", "ends_with", "is_empty", "is_not_empty"}
        date_operators = {
            "within_days", "not_within_days", "is_empty", "is_not_empty",
            "after", "before", "on", "in_the_last", "not_in_the_last",
        }

        for rule in rules:
            if "field" not in rule:
                raise ValueError("Rule missing 'field'")
            if "operator" not in rule:
                raise ValueError("Rule missing 'operator'")

            field = rule["field"]
            operator = rule["operator"]

            # Validate field
            if field not in all_valid_fields:
                raise ValueError(f"Unknown field: {field}")

            # Validate operator
            if operator not in OPERATORS:
                raise ValueError(f"Unknown operator: {operator}")

            # Validate operator/field type compatibility
            if field in DATE_FIELDS and operator not in date_operators:
                raise ValueError(f"Field '{field}' only supports date operators, got '{operator}'")

            # Boolean fields only support equals
            if field in BOOLEAN_FIELDS and operator != "equals":
                raise ValueError(f"Field '{field}' only supports 'equals' operator, got '{operator}'")

            if operator in string_operators and field not in STRING_FIELDS and field not in {"key"}:
                # 'key' is a string field in ANALYSIS_FIELDS
                if field in NUMERIC_FIELDS or field in DATE_FIELDS or field in ANALYSIS_FIELDS:
                    raise ValueError(f"Cannot use string operator '{operator}' on numeric/date field '{field}'")

            # Validate value presence (except for is_empty/is_not_empty)
            if operator not in ("is_empty", "is_not_empty") and "value" not in rule:
                raise ValueError(f"Rule with operator '{operator}' requires 'value'")

    def _build_query(self, playlist: SmartPlaylist, profile_id: UUID) -> Any:
        """Build SQLAlchemy query from playlist rules."""
        # Start with base query
        # Join with latest analysis for feature queries
        needs_analysis = any(
            rule["field"] in ANALYSIS_FIELDS or rule["field"] == "mood_tag"
            for rule in playlist.rules
        )
        needs_play_history = any(
            rule["field"] in PLAY_HISTORY_FIELDS for rule in playlist.rules
        )

        query = select(Track)

        if needs_analysis:
            query = query.join(TrackAnalysis, Track.id == TrackAnalysis.track_id)

        if needs_play_history:
            # Left join with ProfilePlayHistory for the current profile
            # Left join ensures tracks with no play history are included
            query = query.outerjoin(
                ProfilePlayHistory,
                and_(
                    Track.id == ProfilePlayHistory.track_id,
                    ProfilePlayHistory.profile_id == profile_id,
                ),
            )

        # Build conditions from rules
        conditions = []
        for rule in playlist.rules:
            condition = self._build_condition(rule, needs_analysis, needs_play_history)
            if condition is not None:
                conditions.append(condition)

        # Apply conditions with match mode
        if conditions:
            if playlist.match_mode == "any":
                query = query.where(or_(*conditions))
            else:  # "all"
                query = query.where(and_(*conditions))

        return query

    def _build_condition(self, rule: dict[str, Any], has_analysis_join: bool, has_play_history_join: bool = False) -> Any:
        """Build a single condition from a rule."""
        field = rule["field"]
        operator = rule["operator"]
        value = rule.get("value")

        # Handle special "never_played" boolean field
        if field == "never_played":
            if value:  # never_played = true -> tracks with no play history
                return ProfilePlayHistory.track_id.is_(None)
            else:  # never_played = false -> tracks that have been played
                return ProfilePlayHistory.track_id.isnot(None)

        # Handle special "mood_tag" field (JSONB containment on mood_tags)
        if field == "mood_tag" and has_analysis_join:
            import json
            if operator == "equals":
                return TrackAnalysis.mood_tags.op("@>")(
                    json.dumps([{"tag": value}])
                )
            elif operator == "contains":
                return TrackAnalysis.mood_tags.op("@>")(
                    json.dumps([{"tag": value}])
                )
            elif operator == "not_equals":
                return ~TrackAnalysis.mood_tags.op("@>")(
                    json.dumps([{"tag": value}])
                )
            return None

        # Get the column or JSONB path
        if field in TRACK_FIELDS:
            column = getattr(Track, field)
        elif field in ANALYSIS_FIELDS and has_analysis_join:
            # Access typed column
            column = getattr(TrackAnalysis, field)
        elif field in PLAY_HISTORY_FIELDS and has_play_history_join:
            # Play history fields - treat NULL as 0 for numeric comparisons
            if field in ("play_count", "total_play_seconds"):
                column = func.coalesce(getattr(ProfilePlayHistory, field), 0)
            else:
                column = getattr(ProfilePlayHistory, field)
        else:
            return None

        # Check if operator is valid for field type
        string_operators = {"contains", "not_contains", "starts_with", "ends_with", "is_empty", "is_not_empty"}
        if operator in string_operators and field not in STRING_FIELDS and field not in ANALYSIS_FIELDS:
            # Can't use string operators on non-string fields (dates, numbers)
            return None

        # Date fields only support date operators
        date_operators = {
            "within_days", "not_within_days", "is_empty", "is_not_empty",
            "after", "before", "on", "in_the_last", "not_in_the_last",
        }
        if field in DATE_FIELDS and operator not in date_operators:
            return None

        # Build condition based on operator
        if operator == "equals":
            return column == value
        elif operator == "not_equals":
            return column != value
        elif operator == "contains":
            return column.ilike(f"%{value}%")
        elif operator == "not_contains":
            return ~column.ilike(f"%{value}%")
        elif operator == "starts_with":
            return column.ilike(f"{value}%")
        elif operator == "ends_with":
            return column.ilike(f"%{value}")
        elif operator == "greater_than":
            return column > value
        elif operator == "less_than":
            return column < value
        elif operator == "greater_or_equal":
            return column >= value
        elif operator == "less_or_equal":
            return column <= value
        elif operator == "between":
            if isinstance(value, list) and len(value) == 2:
                return and_(column >= value[0], column <= value[1])
            return None
        elif operator == "in":
            if isinstance(value, list):
                return column.in_(value)
            return None
        elif operator == "not_in":
            if isinstance(value, list):
                return ~column.in_(value)
            return None
        elif operator == "is_empty":
            # For play history date fields, NULL means never played
            if field == "last_played_at":
                return column.is_(None)
            return or_(column.is_(None), column == "")
        elif operator == "is_not_empty":
            # For play history date fields, NOT NULL means has been played
            if field == "last_played_at":
                return column.isnot(None)
            return and_(column.isnot(None), column != "")
        elif operator == "within_days":
            # Value can come as string or int from JSON
            try:
                days = int(value) if value is not None else None
                if days is not None:
                    cutoff = utcnow() - timedelta(days=days)
                    return column >= cutoff
            except (ValueError, TypeError):
                pass
            return None
        elif operator == "not_within_days":
            # Tracks NOT played in the last N days (includes never played)
            try:
                days = int(value) if value is not None else None
                if days is not None:
                    cutoff = utcnow() - timedelta(days=days)
                    # Either never played (NULL) or played before the cutoff
                    return or_(column.is_(None), column < cutoff)
            except (ValueError, TypeError):
                pass
            return None
        elif operator == "after":
            # Date is after value (keyword, ISO string)
            resolved = resolve_date_value(value)
            if resolved:
                return column > resolved
            return None
        elif operator == "before":
            # Date is before value (keyword, ISO string)
            resolved = resolve_date_value(value)
            if resolved:
                return column < resolved
            return None
        elif operator == "on":
            # Date matches the same day as value
            resolved = resolve_date_value(value)
            if resolved:
                start = resolved.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)
                return and_(column >= start, column < end)
            return None
        elif operator == "in_the_last":
            # Relative time: {"amount": 3, "unit": "weeks"}
            cutoff = resolve_relative_date(value)
            if cutoff:
                return column >= cutoff
            return None
        elif operator == "not_in_the_last":
            # Not within relative time (includes NULL)
            cutoff = resolve_relative_date(value)
            if cutoff:
                return or_(column.is_(None), column < cutoff)
            return None

        return None

    def _get_order_column(self, order_by: str) -> Any:
        """Get the column to order by."""
        if order_by in TRACK_FIELDS:
            return getattr(Track, order_by)
        elif order_by in ANALYSIS_FIELDS:
            return getattr(TrackAnalysis, order_by)
        elif order_by in ("play_count", "total_play_seconds", "last_played_at"):
            # Play history fields - use coalesce for numeric to sort NULLs as 0
            if order_by in ("play_count", "total_play_seconds"):
                return func.coalesce(getattr(ProfilePlayHistory, order_by), 0)
            return getattr(ProfilePlayHistory, order_by)
        else:
            return Track.title  # Default



    async def convert_to_static(self, playlist: SmartPlaylist, profile_id: UUID) -> tuple[UUID, str, int]:
        """Convert smart playlist to static. Returns (playlist_id, name, track_count)."""
        from app.db.models import Playlist, PlaylistTrack

        # Resolve current tracks
        local_tracks = await self.get_tracks(playlist, limit=10000, offset=0)

        # Create static playlist
        static = Playlist(
            profile_id=profile_id,
            name=playlist.name,
            description=f"Converted from smart playlist: {playlist.description or playlist.name}",
            is_auto_generated=False,
        )
        self.db.add(static)
        await self.db.flush()

        # Add tracks
        for i, track in enumerate(local_tracks):
            pt = PlaylistTrack(
                playlist_id=static.id,
                track_id=track.id,
                position=i,
            )
            self.db.add(pt)

        await self.db.commit()
        return static.id, static.name, len(local_tracks)

    async def import_playlist_file(self, profile_id: UUID, data: dict) -> tuple[UUID, str, int, int]:
        """Import .familiar playlist file. Returns (playlist_id, name, matched_count, total_tracks)."""
        playlist_data = data.get("playlist", {})
        name = playlist_data.get("name", "Imported Playlist")
        description = playlist_data.get("description")
        playlist_type = playlist_data.get("type", "smart")
        rules = playlist_data.get("rules", [])
        match_mode = playlist_data.get("match_mode", "all")
        imported_tracks = playlist_data.get("tracks", [])

        # Match tracks to local library
        matched_count = 0
        for track_info in imported_tracks:
            title = track_info.get("title", "").lower()
            artist = track_info.get("artist", "").lower()

            if not title or not artist:
                continue

            # Try to find matching track
            result = await self.db.execute(
                select(Track).where(
                    Track.title.ilike(f"%{title}%"),
                    Track.artist.ilike(f"%{artist}%"),
                ).limit(1)
            )
            track = result.scalar_one_or_none()
            if track:
                matched_count += 1

        # If it's a smart playlist with rules, use those rules
        # Otherwise, create rules based on the track metadata
        if playlist_type == "smart" and rules:
            playlist = await self.create(
                profile_id=profile_id,
                name=name,
                description=description,
                rules=rules,
                match_mode=match_mode,
            )
        else:
            # Create a smart playlist with artist rules from imported tracks
            unique_artists = list(set(
                t.get("artist") for t in imported_tracks
                if t.get("artist")
            ))[:20]  # Limit to 20 artists

            if unique_artists:
                artist_rules = [
                    {"field": "artist", "operator": "contains", "value": artist}
                    for artist in unique_artists
                ]
                playlist = await self.create(
                    profile_id=profile_id,
                    name=name,
                    description=description or f"Imported playlist with {len(imported_tracks)} tracks",
                    rules=artist_rules,
                    match_mode="any",  # Match any of the artists
                )
            else:
                # Fallback: create empty playlist
                playlist = await self.create(
                    profile_id=profile_id,
                    name=name,
                    description=description,
                    rules=[],
                    match_mode="all",
                )

        return playlist.id, playlist.name, matched_count, len(imported_tracks)


async def get_smart_playlist_service(db: AsyncSession) -> SmartPlaylistService:
    """Factory function for dependency injection."""
    return SmartPlaylistService(db)
