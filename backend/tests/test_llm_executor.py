"""Tests for the LLM tool executor service.

Tests cover tool dispatching, helper methods, and individual tool handlers.
Uses mocked database sessions to test logic in isolation.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.llm.executor import ToolExecutor
from app.services.llm.tools import MUSIC_TOOLS


class TestToolExecutorDispatch:
    """Tests for tool dispatch logic."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        return db

    @pytest.fixture
    def executor(self, mock_db):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(db=mock_db, profile_id=uuid4(), user_message="test request")

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_error(self, executor):
        """Unknown tool names should return error dict."""
        result = await executor.execute("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_correct_handler(self, executor):
        """Tool names should dispatch to correct handlers."""
        # Patch the handler to verify it gets called
        with patch.object(executor, "_search_library", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = {"tracks": [], "count": 0}
            await executor.execute("search_library", {"query": "test"})
            mock_handler.assert_called_once_with(query="test")

    @pytest.mark.asyncio
    async def test_execute_no_args_tools(self, executor):
        """Tools with no args should work correctly."""
        with patch.object(executor, "_get_library_stats", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = {"total_tracks": 100}
            await executor.execute("get_library_stats", {})
            mock_handler.assert_called_once_with()


class TestHelperMethods:
    """Tests for ToolExecutor helper methods."""

    @pytest.fixture
    def executor(self):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(db=AsyncMock(), profile_id=uuid4())

    def test_normalize_query_variations_basic(self, executor):
        """Basic query should return itself."""
        variations = executor._normalize_query_variations("test query")
        assert "test query" in variations

    def test_normalize_query_variations_pads_single_digits(self, executor):
        """Single digits should be padded with zero."""
        variations = executor._normalize_query_variations("track 1 album")
        assert "track 01 album" in variations

    def test_normalize_query_variations_unpads_zero_prefix(self, executor):
        """Zero-prefixed digits should be unpadded."""
        variations = executor._normalize_query_variations("track 01 album")
        assert "track 1 album" in variations

    def test_track_to_dict_converts_all_fields(self, executor):
        """Track should be converted to dict with all fields."""
        mock_track = MagicMock()
        mock_track.id = uuid4()
        mock_track.title = "Test Title"
        mock_track.artist = "Test Artist"
        mock_track.album = "Test Album"
        mock_track.genre = "Rock"
        mock_track.duration_seconds = 180
        mock_track.year = 2024

        result = executor._track_to_dict(mock_track)

        assert result["id"] == str(mock_track.id)
        assert result["title"] == "Test Title"
        assert result["artist"] == "Test Artist"
        assert result["album"] == "Test Album"
        assert result["genre"] == "Rock"
        assert result["duration_seconds"] == 180
        assert result["year"] == 2024

    def test_apply_diversity_limits_per_artist(self, executor):
        """Diversity filter should limit tracks per artist."""
        # Create tracks from same artist
        tracks = []
        for i in range(5):
            track = MagicMock()
            track.artist = "Same Artist"
            track.album = f"Album {i}"
            tracks.append(track)

        result = executor._apply_diversity(tracks, max_per_artist=2, max_per_album=10)
        assert len(result) == 2

    def test_apply_diversity_limits_per_album(self, executor):
        """Diversity filter should limit tracks per album."""
        # Create tracks from same album
        tracks = []
        for i in range(5):
            track = MagicMock()
            track.artist = "Same Artist"
            track.album = "Same Album"
            tracks.append(track)

        result = executor._apply_diversity(tracks, max_per_artist=10, max_per_album=2)
        assert len(result) == 2

    def test_apply_diversity_preserves_varied_tracks(self, executor):
        """Diversity filter should keep all tracks when varied."""
        tracks = []
        for i in range(5):
            track = MagicMock()
            track.artist = f"Artist {i}"
            track.album = f"Album {i}"
            tracks.append(track)

        result = executor._apply_diversity(tracks, max_per_artist=2, max_per_album=2)
        assert len(result) == 5

    def test_playlist_name_strips_filler_words(self, executor):
        """Playlist name should strip common filler phrases from the user message."""
        executor.user_message = "play me some chill electronic music"
        name = executor._playlist_name_from_request()
        assert "chill electronic" in name.lower()


class TestQueuedTracksState:
    """Tests for queued tracks state management."""

    @pytest.fixture
    def executor(self):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(db=AsyncMock(), profile_id=uuid4())

    def test_get_queued_tracks_initially_empty(self, executor):
        """Initially no tracks should be queued."""
        tracks, clear_queue = executor.get_queued_tracks()
        assert tracks == []
        assert clear_queue is True

    def test_get_playback_action_initially_none(self, executor):
        """Initially no playback action should be set."""
        assert executor.get_playback_action() is None

    def test_get_auto_saved_playlist_initially_none(self, executor):
        """Initially no auto-saved playlist should exist."""
        assert executor.get_auto_saved_playlist() is None


class TestSearchLibrary:
    """Tests for _search_library tool."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(db=mock_db, profile_id=uuid4())

    @pytest.mark.asyncio
    async def test_search_library_returns_dict_with_tracks(self, executor, mock_db):
        """Search should return dict with tracks and count."""
        # Mock empty result
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await executor._search_library("test query")

        assert "tracks" in result
        assert "count" in result
        assert isinstance(result["tracks"], list)

    @pytest.mark.asyncio
    async def test_search_library_handles_string_limit(self, executor, mock_db):
        """Search should handle limit passed as string."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        # Should not raise even with string limit
        result = await executor._search_library("test", limit="20")
        assert "count" in result

    @pytest.mark.asyncio
    async def test_search_library_applies_diversity(self, executor, mock_db):
        """Search should apply diversity filtering."""
        # Create mock tracks from same artist
        tracks = []
        for i in range(10):
            track = MagicMock()
            track.id = uuid4()
            track.title = f"Track {i}"
            track.artist = "Same Artist"
            track.album = f"Album {i}"
            track.genre = "Rock"
            track.duration_seconds = 180
            track.year = 2024
            tracks.append(track)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = tracks
        mock_db.execute.return_value = mock_result

        result = await executor._search_library("test", limit=10)

        # Should have at most 2 per artist due to diversity filter
        assert result["count"] <= 2


class TestControlPlayback:
    """Tests for _control_playback tool."""

    @pytest.fixture
    def executor(self):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(db=AsyncMock(), profile_id=uuid4())

    @pytest.mark.asyncio
    async def test_control_playback_sets_action(self, executor):
        """Control playback should set the playback action."""
        result = await executor._control_playback("play")

        assert result["action"] == "play"
        assert result["status"] == "ok"
        assert executor.get_playback_action() == "play"

    @pytest.mark.asyncio
    async def test_control_playback_pause(self, executor):
        """Pause action should be tracked."""
        await executor._control_playback("pause")
        assert executor.get_playback_action() == "pause"

    @pytest.mark.asyncio
    async def test_control_playback_next(self, executor):
        """Next action should be tracked."""
        await executor._control_playback("next")
        assert executor.get_playback_action() == "next"


class TestQueueTracks:
    """Tests for _queue_tracks tool."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        return db

    @pytest.fixture
    def executor(self, mock_db):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(db=mock_db, profile_id=uuid4(), user_message="play some music")

    @pytest.mark.asyncio
    async def test_queue_tracks_stores_tracks(self, executor, mock_db):
        """Queuing should store tracks in internal state."""
        track_id = uuid4()
        mock_track = MagicMock()
        mock_track.id = track_id
        mock_track.title = "Test Track"
        mock_track.artist = "Test Artist"
        mock_track.album = "Test Album"
        mock_track.genre = "Rock"
        mock_track.duration_seconds = 180
        mock_track.year = 2024

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_track]
        mock_db.execute.return_value = mock_result
        mock_db.get = AsyncMock(return_value=mock_track)

        result = await executor._queue_tracks([str(track_id)])

        assert result["queued"] == 1
        assert len(result["tracks"]) == 1

        # Check internal state
        queued, _ = executor.get_queued_tracks()
        assert len(queued) == 1

    @pytest.mark.asyncio
    async def test_queue_tracks_empty_list(self, executor, mock_db):
        """Queuing empty list should work without error."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await executor._queue_tracks([])

        assert result["queued"] == 0


class TestGetLibraryStats:
    """Tests for _get_library_stats tool."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(db=mock_db)

    @pytest.mark.asyncio
    async def test_get_library_stats_returns_all_fields(self, executor, mock_db):
        """Stats should return all expected fields."""
        # Mock the database calls
        mock_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=1000)),  # total tracks
            MagicMock(scalar=MagicMock(return_value=100)),   # total artists
            MagicMock(scalar=MagicMock(return_value=200)),   # total albums
            MagicMock(all=MagicMock(return_value=[("Rock", 500), ("Jazz", 300)])),  # genres
        ]

        result = await executor._get_library_stats()

        assert "total_tracks" in result
        assert "total_artists" in result
        assert "total_albums" in result
        assert "top_genres" in result


class TestSelectDiverseTracks:
    """Tests for _select_diverse_tracks tool."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(db=mock_db)

    @pytest.mark.asyncio
    async def test_select_diverse_empty_input(self, executor):
        """Empty track list should return empty result."""
        result = await executor._select_diverse_tracks([])

        assert result["tracks"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_select_diverse_applies_filters(self, executor, mock_db):
        """Should apply diversity filters to selection."""
        # Create tracks from same artist
        tracks = []
        for i in range(10):
            track = MagicMock()
            track.id = uuid4()
            track.title = f"Track {i}"
            track.artist = "Same Artist"
            track.album = f"Album {i}"
            track.genre = "Rock"
            track.duration_seconds = 180
            track.year = 2024
            tracks.append(track)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = tracks
        mock_db.execute.return_value = mock_result

        track_ids = [str(t.id) for t in tracks]
        result = await executor._select_diverse_tracks(
            track_ids, limit=10, max_per_artist=2, max_per_album=2
        )

        # Should have at most 2 per artist
        assert result["count"] <= 2


class TestMusicTools:
    """Tests for MUSIC_TOOLS definitions."""

    def test_all_tools_have_required_fields(self):
        """All tools should have name, description, input_schema."""
        for tool in MUSIC_TOOLS:
            assert "name" in tool, f"Tool missing name: {tool}"
            assert "description" in tool, f"Tool missing description: {tool}"
            assert "input_schema" in tool, f"Tool missing input_schema: {tool}"

    def test_tool_names_are_unique(self):
        """All tool names should be unique."""
        names = [tool["name"] for tool in MUSIC_TOOLS]
        assert len(names) == len(set(names))

    def test_required_tools_present(self):
        """Essential tools should be present."""
        tool_names = {tool["name"] for tool in MUSIC_TOOLS}

        essential_tools = {
            "search_library",
            "find_similar_tracks",
            "filter_tracks",
            "queue_tracks",
            "control_playback",
            "get_library_stats",
        }

        for tool in essential_tools:
            assert tool in tool_names, f"Essential tool missing: {tool}"


class TestFilterTracks:
    """Tests for _filter_tracks tool (formerly _filter_tracks_by_features)."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(db=mock_db, profile_id=uuid4())

    @pytest.fixture
    def executor_no_profile(self, mock_db):
        """Create a ToolExecutor without profile."""
        return ToolExecutor(db=mock_db, profile_id=None)

    def _mock_empty_result(self, mock_db):
        """Set up mock_db to return empty results."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

    @pytest.mark.asyncio
    async def test_filter_handles_string_params(self, executor, mock_db):
        """Filter should handle params passed as strings."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(
            bpm_min="100",
            bpm_max="120",
            energy_min="0.5",
            limit="20"
        )

        assert "tracks" in result
        assert "count" in result

    @pytest.mark.asyncio
    async def test_filter_handles_none_params(self, executor, mock_db):
        """Filter should handle None params gracefully."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(
            bpm_min=None,
            bpm_max=None,
            energy_min=None
        )

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_genre_ilike(self, executor, mock_db):
        """Genre filter should use case-insensitive partial match."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(genre="electronic")

        assert "tracks" in result
        # Verify the query was executed (genre filter doesn't need TrackAnalysis join)
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_artist_ilike(self, executor, mock_db):
        """Artist filter should use case-insensitive partial match."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(artist="radiohead")

        assert "tracks" in result
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_year_range(self, executor, mock_db):
        """Year range filter should work correctly."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(year_min=1990, year_max=1999)

        assert "tracks" in result
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_year_range_string_coercion(self, executor, mock_db):
        """Year range should handle string values from LLM."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(year_min="1990", year_max="1999")

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_is_favorite_true(self, executor, mock_db):
        """is_favorite=True should join ProfileFavorite."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(is_favorite=True)

        assert "tracks" in result
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_is_favorite_string_coercion(self, executor, mock_db):
        """is_favorite should handle string 'true' from LLM."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(is_favorite="true")

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_is_favorite_without_profile(self, executor_no_profile, mock_db):
        """is_favorite without profile should skip the join gracefully."""
        self._mock_empty_result(mock_db)

        # Should not error even without profile_id
        result = await executor_no_profile._filter_tracks(is_favorite=True)

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_min_play_count(self, executor, mock_db):
        """min_play_count should filter on coalesced play_count."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(min_play_count=5)

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_max_play_count_zero(self, executor, mock_db):
        """max_play_count=0 should find never-played tracks (NULL play history)."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(max_play_count=0)

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_max_play_count_positive(self, executor, mock_db):
        """max_play_count > 0 should use coalesced comparison."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(max_play_count=3)

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_not_played_in_days(self, executor, mock_db):
        """not_played_in_days should find tracks with NULL or old last_played_at."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(not_played_in_days=30)

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_played_in_last_days(self, executor, mock_db):
        """played_in_last_days should filter recent plays."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(played_in_last_days=7)

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_added_in_last_days(self, executor, mock_db):
        """added_in_last_days should filter on created_at."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(added_in_last_days=14)

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_sort_by_play_count(self, executor, mock_db):
        """sort_by=play_count should order results (desc by default)."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(sort_by="play_count")

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_sort_by_title_asc(self, executor, mock_db):
        """sort_by=title should order by title (asc by default)."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(sort_by="title", sort_order="asc")

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_filter_sort_preserves_order_through_diversity(self, executor, mock_db):
        """When sort_by is set (not random), diversity filter should not shuffle."""
        # Create tracks with distinct artists so diversity keeps them all
        tracks = []
        for i in range(5):
            track = MagicMock()
            track.id = uuid4()
            track.title = f"Track {i}"
            track.artist = f"Artist {i}"
            track.album = f"Album {i}"
            track.genre = "Rock"
            track.duration_seconds = 180
            track.year = 2000 + i
            tracks.append(track)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = tracks
        mock_db.execute.return_value = mock_result

        result = await executor._filter_tracks(sort_by="recently_added")

        # With distinct artists, all tracks should be returned
        assert result["count"] == 5

    @pytest.mark.asyncio
    async def test_filter_combined_criteria(self, executor, mock_db):
        """Should support combining library criteria and audio features."""
        self._mock_empty_result(mock_db)

        result = await executor._filter_tracks(
            genre="electronic",
            year_min=1990,
            year_max=1999,
            energy_min=0.7,
            is_favorite=True,
        )

        assert "tracks" in result

    @pytest.mark.asyncio
    async def test_backwards_compat_alias(self, executor, mock_db):
        """filter_tracks_by_features should still dispatch correctly."""
        self._mock_empty_result(mock_db)

        # Use the old tool name through the execute dispatcher
        with patch.object(executor, "_filter_tracks", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = {"tracks": [], "count": 0}
            await executor.execute("filter_tracks_by_features", {"bpm_min": 100})
            mock_handler.assert_called_once_with(bpm_min=100)


class TestPlaylistNameGeneration:
    """Tests for playlist name generation."""

    @pytest.fixture
    def executor(self):
        """Create a ToolExecutor with mock db."""
        return ToolExecutor(
            db=AsyncMock(),
            profile_id=uuid4(),
            user_message="play some chill electronic music"
        )

    def test_fallback_uses_user_message(self, executor):
        """Fallback should use user message."""
        name = executor._playlist_name_from_request()
        assert "chill electronic" in name.lower()

    def test_fallback_truncates_long_message(self):
        """Fallback should truncate long messages."""
        long_message = "a" * 100
        executor = ToolExecutor(
            db=AsyncMock(),
            profile_id=uuid4(),
            user_message=long_message
        )

        name = executor._playlist_name_from_request()
        assert len(name) <= 54  # 50 chars + "..."

    def test_fallback_with_no_message(self):
        """Fallback should generate timestamp-based name."""
        executor = ToolExecutor(db=AsyncMock(), profile_id=uuid4(), user_message="")
        name = executor._playlist_name_from_request()
        assert "AI Playlist" in name


class TestGetLibraryGenres:
    """Tests for _get_library_genres tool."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db)

    @pytest.mark.asyncio
    async def test_returns_genres_with_counts(self, executor, mock_db):
        """Should return genre list with track counts."""
        mock_result = MagicMock()
        mock_result.all.return_value = [("Rock", 500), ("Jazz", 300), ("Electronic", 150)]
        mock_db.execute.return_value = mock_result

        result = await executor._get_library_genres()

        assert result["total"] == 3
        assert result["genres"][0] == {"genre": "Rock", "count": 500}
        assert result["genres"][1] == {"genre": "Jazz", "count": 300}
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_string_limit_coercion(self, executor, mock_db):
        """Should handle limit passed as string."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await executor._get_library_genres(limit="25")

        assert result["total"] == 0
        assert result["genres"] == []


class TestGetTrackDetails:
    """Tests for _get_track_details tool."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db)

    @pytest.mark.asyncio
    async def test_found_with_analysis(self, executor, mock_db):
        """Should return track with features when analysis exists."""
        track_id = uuid4()
        mock_track = MagicMock()
        mock_track.id = track_id
        mock_track.title = "Test"
        mock_track.artist = "Artist"
        mock_track.album = "Album"
        mock_track.genre = "Rock"
        mock_track.duration_seconds = 200
        mock_track.year = 2020

        mock_analysis = MagicMock()
        mock_analysis.to_features_dict.return_value = {"bpm": 120, "key": "C"}

        # First call: track lookup, second: analysis lookup
        mock_db.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_track)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_analysis)),
        ]

        result = await executor._get_track_details(str(track_id))

        assert result["title"] == "Test"
        assert result["features"] == {"bpm": 120, "key": "C"}

    @pytest.mark.asyncio
    async def test_not_found(self, executor, mock_db):
        """Should return error when track not found."""
        mock_db.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        )

        result = await executor._get_track_details(str(uuid4()))

        assert "error" in result
        assert "not found" in result["error"]


class TestGetAlbumTracks:
    """Tests for _get_album_tracks tool."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db)

    @pytest.mark.asyncio
    async def test_returns_album_info(self, executor, mock_db):
        """Should return album metadata with tracks."""
        tracks = []
        for i in range(3):
            t = MagicMock()
            t.id = uuid4()
            t.title = f"Track {i + 1}"
            t.artist = "Artist"
            t.album = "Test Album"
            t.album_artist = "Artist"
            t.track_number = i + 1
            t.disc_number = 1
            tracks.append(t)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = tracks
        mock_db.execute.return_value = mock_result

        result = await executor._get_album_tracks("Test Album")

        assert result["album"] == "Test Album"
        assert result["count"] == 3
        assert result["album_artist"] == "Artist"
        assert result["is_multi_artist"] is False
        assert len(result["track_ids"]) == 3

    @pytest.mark.asyncio
    async def test_with_artist_filter(self, executor, mock_db):
        """Should filter by artist when provided."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await executor._get_album_tracks("Album", artist="Specific Artist")

        assert result["count"] == 0
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_album(self, executor, mock_db):
        """Should return empty when no tracks found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await executor._get_album_tracks("Nonexistent Album")

        assert result["count"] == 0
        assert result["tracks"] == []


class TestFindDuplicateArtists:
    """Tests for _find_duplicate_artists tool."""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db)

    @pytest.mark.asyncio
    async def test_no_duplicates(self, executor, mock_db):
        """Should report no duplicates found."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(artist="Artist A", track_count=10),
            MagicMock(artist="Artist B", track_count=5),
        ]
        mock_db.execute.return_value = mock_result

        result = await executor._find_duplicate_artists()

        assert result["found"] == 0

    @pytest.mark.asyncio
    async def test_finds_case_variants(self, executor, mock_db):
        """Should find case-variant duplicates."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(artist="Radiohead", track_count=50),
            MagicMock(artist="radiohead", track_count=3),
            MagicMock(artist="Other Band", track_count=10),
        ]
        mock_db.execute.return_value = mock_result

        result = await executor._find_duplicate_artists()

        assert result["found"] == 1
        assert result["duplicates"][0]["canonical"] == "Radiohead"
        assert len(result["duplicates"][0]["variants"]) == 2

    @pytest.mark.asyncio
    async def test_artist_hint_filter(self, executor, mock_db):
        """Should only include groups matching artist_hint."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(artist="Radiohead", track_count=50),
            MagicMock(artist="radiohead", track_count=3),
            MagicMock(artist="The Beatles", track_count=30),
            MagicMock(artist="the beatles", track_count=2),
        ]
        mock_db.execute.return_value = mock_result

        result = await executor._find_duplicate_artists(artist_hint="radiohead")

        assert result["found"] == 1
        assert result["duplicates"][0]["canonical"] == "Radiohead"


class TestMergeDuplicateArtists:
    """Tests for _merge_duplicate_artists tool."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db, profile_id=uuid4())

    @pytest.mark.asyncio
    async def test_creates_proposed_change(self, executor, mock_db):
        """Should create a proposed change to merge artists."""
        track = MagicMock()
        track.id = uuid4()
        track.artist = "radiohead"

        # First: merge query, second: propose_metadata_change track lookup
        mock_db.execute.side_effect = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[track])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[track])))),
        ]

        result = await executor._merge_duplicate_artists(
            source_artist="radiohead",
            target_artist="Radiohead",
            reason="Normalize capitalization",
        )

        assert result["status"] == "proposed"
        assert result["field"] == "artist"
        mock_db.add.assert_called()

    @pytest.mark.asyncio
    async def test_source_not_found(self, executor, mock_db):
        """Should return error when source artist has no tracks."""
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        result = await executor._merge_duplicate_artists(
            source_artist="nonexistent",
            target_artist="Target",
            reason="test",
        )

        assert "error" in result


class TestMarkAlbumAsCompilation:
    """Tests for _mark_album_as_compilation tool."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db, profile_id=uuid4())

    @pytest.mark.asyncio
    async def test_creates_change(self, executor, mock_db):
        """Should propose album_artist change for compilation."""
        track = MagicMock()
        track.id = uuid4()
        track.title = "Track 1"
        track.artist = "Artist 1"
        track.album = "Various Artists"
        track.album_artist = None
        track.track_number = 1
        track.disc_number = 1

        # First: get_album_tracks, second: propose_metadata_change track lookup
        mock_db.execute.side_effect = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[track])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[track])))),
        ]

        result = await executor._mark_album_as_compilation(
            album="Various Artists",
            album_artist="Various Artists",
            reason="Compilation album",
        )

        assert result["status"] == "proposed"
        assert result["field"] == "album_artist"

    @pytest.mark.asyncio
    async def test_empty_album(self, executor, mock_db):
        """Should return error when album has no tracks."""
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        result = await executor._mark_album_as_compilation(
            album="nonexistent",
            album_artist="VA",
            reason="test",
        )

        assert "error" in result


class TestProposeMetadataChange:
    """Tests for _propose_metadata_change tool."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db, profile_id=uuid4())

    @pytest.mark.asyncio
    async def test_valid_field(self, executor, mock_db):
        """Should create change for valid field."""
        track = MagicMock()
        track.id = uuid4()
        track.genre = "Rock"

        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[track])))
        )

        result = await executor._propose_metadata_change(
            track_ids=[str(track.id)],
            field="genre",
            new_value="Alternative Rock",
            reason="More specific genre",
        )

        assert result["status"] == "proposed"
        assert result["field"] == "genre"
        assert result["tracks_affected"] == 1
        assert "_navigate" in result

    @pytest.mark.asyncio
    async def test_invalid_field(self, executor, mock_db):
        """Should reject invalid field names."""
        result = await executor._propose_metadata_change(
            track_ids=[str(uuid4())],
            field="invalid_field",
            new_value="test",
            reason="test",
        )

        assert "error" in result
        assert "Invalid field" in result["error"]

    @pytest.mark.asyncio
    async def test_empty_ids(self, executor, mock_db):
        """Should reject empty track IDs."""
        result = await executor._propose_metadata_change(
            track_ids=[],
            field="genre",
            new_value="test",
            reason="test",
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_year_coercion(self, executor, mock_db):
        """Should convert year field to int."""
        track = MagicMock()
        track.id = uuid4()
        track.year = 2020

        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[track])))
        )

        result = await executor._propose_metadata_change(
            track_ids=[str(track.id)],
            field="year",
            new_value="2021",
            reason="Wrong year",
        )

        assert result["status"] == "proposed"
        assert result["new_value"] == 2021


class TestSaveAsPlaylist:
    """Tests for _save_as_playlist tool."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        return db

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db, profile_id=uuid4(), user_message="test")

    @pytest.mark.asyncio
    async def test_creates_playlist_with_tracks(self, executor, mock_db):
        """Should create playlist and add tracks."""
        track_id = uuid4()
        mock_track = MagicMock()
        mock_track.id = track_id

        mock_db.get = AsyncMock(return_value=mock_track)

        result = await executor._save_as_playlist(
            name="My Playlist",
            track_ids=[str(track_id)],
            description="A test playlist",
        )

        assert result["saved"] is True
        assert result["playlist_name"] == "My Playlist"
        assert result["tracks_saved"] == 1

    @pytest.mark.asyncio
    async def test_no_profile(self, mock_db):
        """Should fail without profile."""
        executor = ToolExecutor(db=mock_db, profile_id=None)

        result = await executor._save_as_playlist(
            name="Test", track_ids=[str(uuid4())]
        )

        assert result["saved"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_empty_tracks(self, mock_db):
        """Should fail with empty track list."""
        executor = ToolExecutor(db=mock_db, profile_id=uuid4())

        result = await executor._save_as_playlist(name="Test", track_ids=[])

        assert result["saved"] is False


class TestNormalizeArtistForComparison:
    """Tests for _normalize_artist_for_comparison helper."""

    @pytest.fixture
    def executor(self):
        return ToolExecutor(db=AsyncMock())

    def test_normalizes_case_and_conjunctions(self, executor):
        """Should normalize &, +, case, and whitespace."""
        assert executor._normalize_artist_for_comparison("Simon & Garfunkel") == "simon and garfunkel"
        assert executor._normalize_artist_for_comparison("Simon + Garfunkel") == "simon and garfunkel"
        assert executor._normalize_artist_for_comparison("SIMON  &  GARFUNKEL") == "simon and garfunkel"

    def test_normalizes_separators(self, executor):
        """Should normalize underscores and hyphens."""
        assert executor._normalize_artist_for_comparison("My_Artist-Name") == "my artist name"

    def test_empty_string(self, executor):
        """Should handle empty artist string."""
        assert executor._normalize_artist_for_comparison("") == ""


class TestSafeParseUuids:
    """Tests for _safe_parse_uuids helper."""

    @pytest.fixture
    def executor(self):
        return ToolExecutor(db=AsyncMock())

    def test_valid_uuids(self, executor):
        """Should parse valid UUIDs."""
        id1, id2 = uuid4(), uuid4()
        result = executor._safe_parse_uuids([str(id1), str(id2)])
        assert result == [id1, id2]

    def test_skips_invalid_uuids(self, executor):
        """Should skip invalid strings and return only valid UUIDs."""
        valid_id = uuid4()
        result = executor._safe_parse_uuids([str(valid_id), "not-a-uuid", "12345"])
        assert len(result) == 1
        assert result[0] == valid_id

    def test_all_invalid_returns_empty(self, executor):
        """Should return empty list when all IDs are invalid."""
        result = executor._safe_parse_uuids(["bad", "also-bad", "123"])
        assert result == []

    def test_empty_list(self, executor):
        """Should handle empty input."""
        assert executor._safe_parse_uuids([]) == []


class TestInvalidUuidHandling:
    """Tests that tool methods handle invalid UUIDs gracefully."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db, profile_id=uuid4(), user_message="test")

    @pytest.mark.asyncio
    async def test_queue_tracks_invalid_uuids(self, executor, mock_db):
        """queue_tracks should handle invalid UUIDs without crashing."""
        result = await executor._queue_tracks(["not-a-uuid", "also-bad"])
        assert result["queued"] == 0
        # Should NOT have hit the database
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_select_diverse_tracks_invalid_uuids(self, executor):
        """select_diverse_tracks should handle invalid UUIDs without crashing."""
        result = await executor._select_diverse_tracks(["bad-id", "worse-id"])
        assert result["count"] == 0
        assert result["tracks"] == []

    @pytest.mark.asyncio
    async def test_propose_metadata_change_invalid_uuids(self, executor):
        """propose_metadata_change should handle invalid UUIDs without crashing."""
        result = await executor._propose_metadata_change(
            track_ids=["not-a-uuid"],
            field="genre",
            new_value="Rock",
            reason="test",
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_queue_tracks_mixed_valid_invalid(self, executor, mock_db):
        """queue_tracks should use only valid UUIDs when mixed with invalid."""
        valid_id = uuid4()
        mock_track = MagicMock()
        mock_track.id = valid_id
        mock_track.title = "Test"
        mock_track.artist = "Artist"
        mock_track.album = "Album"
        mock_track.genre = "Rock"
        mock_track.duration_seconds = 180
        mock_track.year = 2024

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_track]
        mock_db.execute.return_value = mock_result
        mock_db.get = AsyncMock(return_value=mock_track)

        result = await executor._queue_tracks([str(valid_id), "invalid-id"])

        assert result["queued"] == 1


class TestExecuteExceptionHandling:
    """Tests that execute() catches exceptions and rolls back."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.rollback = AsyncMock()
        return db

    @pytest.fixture
    def executor(self, mock_db):
        return ToolExecutor(db=mock_db, profile_id=uuid4())

    @pytest.mark.asyncio
    async def test_execute_catches_handler_exception(self, executor, mock_db):
        """execute() should catch exceptions and return error dict."""
        with patch.object(executor, "_search_library", new_callable=AsyncMock) as mock_handler:
            mock_handler.side_effect = RuntimeError("something broke")
            result = await executor.execute("search_library", {"query": "test"})

        assert "error" in result
        assert "RuntimeError" in result["error"]
        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_handles_rollback_failure(self, executor, mock_db):
        """execute() should not crash even if rollback fails."""
        mock_db.rollback.side_effect = Exception("rollback failed too")

        with patch.object(executor, "_search_library", new_callable=AsyncMock) as mock_handler:
            mock_handler.side_effect = RuntimeError("something broke")
            result = await executor.execute("search_library", {"query": "test"})

        assert "error" in result
        assert "RuntimeError" in result["error"]
