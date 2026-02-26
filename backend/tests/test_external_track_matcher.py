"""Tests for external track matching - normalization and matching logic."""

from app.services.external_track_matcher import normalize_for_matching


class TestNormalizeForMatching:
    """Tests for the normalize_for_matching helper."""

    def test_basic_lowercase(self):
        assert normalize_for_matching("Hello World") == "hello world"

    def test_strips_whitespace(self):
        assert normalize_for_matching("  hello  world  ") == "hello world"

    def test_removes_feat_parentheses(self):
        result = normalize_for_matching("Song Name (feat. Other Artist)")
        assert result == "song name"

    def test_removes_ft_parentheses(self):
        result = normalize_for_matching("Song Name (ft. Other Artist)")
        assert result == "song name"

    def test_removes_featuring_brackets(self):
        result = normalize_for_matching("Song Name [featuring Other Artist]")
        assert result == "song name"

    def test_removes_remaster_annotation(self):
        result = normalize_for_matching("Song Name (2020 Remaster)")
        assert result == "song name"

    def test_removes_remix_annotation(self):
        result = normalize_for_matching("Song Name (Club Remix)")
        assert result == "song name"

    def test_removes_deluxe_annotation(self):
        result = normalize_for_matching("Album Name (Deluxe Edition)")
        assert result == "album name"

    def test_removes_bonus_annotation(self):
        result = normalize_for_matching("Album Name [Bonus Tracks]")
        assert result == "album name"

    def test_normalizes_backtick(self):
        result = normalize_for_matching("Don`t Stop Me Now")
        assert "'" in result
        assert "`" not in result

    def test_preserves_apostrophe(self):
        result = normalize_for_matching("Don't Stop")
        assert "'" in result

    def test_preserves_regular_text(self):
        assert normalize_for_matching("Simple Title") == "simple title"

    def test_multiple_annotations(self):
        result = normalize_for_matching("Song (feat. A) [Remastered Version]")
        assert result == "song"

    def test_empty_string(self):
        assert normalize_for_matching("") == ""

    def test_case_insensitive_feat(self):
        result = normalize_for_matching("Song (FEAT. Artist)")
        assert result == "song"

    # --- Dash-prefixed suffix stripping (Spotify style) ---

    def test_dash_remaster_with_year(self):
        assert normalize_for_matching("Suedehead - 2011 Remaster") == "suedehead"

    def test_dash_remaster_with_year_2(self):
        assert normalize_for_matching("Today - 2011 Remaster") == "today"

    def test_dash_remastered_with_year(self):
        assert normalize_for_matching("Stupid Girl - Remastered 2015") == "stupid girl"

    def test_dash_radio_edit(self):
        assert normalize_for_matching("Blind - Radio Edit") == "blind"

    def test_dash_deluxe_version(self):
        assert normalize_for_matching("Song - Deluxe Version") == "song"

    def test_dash_remastered(self):
        assert normalize_for_matching("Song - Remastered") == "song"
