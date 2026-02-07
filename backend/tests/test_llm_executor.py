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

        # Mock the playlist name generation
        with patch.object(executor, "_generate_playlist_name_llm", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Test Playlist"
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


class TestGetSpotifyStatus:
    """Tests for Spotify-related tools."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_spotify_status_no_profile(self, mock_db):
        """Spotify status should handle no profile ID."""
        executor = ToolExecutor(db=mock_db, profile_id=None)
        result = await executor._get_spotify_status()

        assert result["connected"] is False
        assert "message" in result

    @pytest.mark.asyncio
    async def test_spotify_status_not_connected(self, mock_db):
        """Spotify status should handle unconnected profile."""
        executor = ToolExecutor(db=mock_db, profile_id=uuid4())

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await executor._get_spotify_status()

        assert result["connected"] is False


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
        name = executor._generate_playlist_name_fallback()
        assert "chill electronic" in name.lower()

    def test_fallback_truncates_long_message(self):
        """Fallback should truncate long messages."""
        long_message = "a" * 100
        executor = ToolExecutor(
            db=AsyncMock(),
            profile_id=uuid4(),
            user_message=long_message
        )

        name = executor._generate_playlist_name_fallback()
        assert len(name) <= 54  # 50 chars + "..."

    def test_fallback_with_no_message(self):
        """Fallback should generate timestamp-based name."""
        executor = ToolExecutor(db=AsyncMock(), profile_id=uuid4(), user_message="")
        name = executor._generate_playlist_name_fallback()
        assert "AI Playlist" in name
