"""Tests for normalize_for_duplicate_matching()."""

from app.services.normalize import normalize_for_duplicate_matching


class TestNormalizeForDuplicateMatching:
    """Test the duplicate-matching normalizer."""

    def test_empty_and_none(self):
        assert normalize_for_duplicate_matching(None) == ""
        assert normalize_for_duplicate_matching("") == ""

    def test_inherits_base_normalization(self):
        # Diacritics
        assert normalize_for_duplicate_matching("Björk") == "bjork"
        # Dashes
        assert normalize_for_duplicate_matching("Rock \u2014 Roll") == "rock - roll"
        # Case folding
        assert normalize_for_duplicate_matching("HELLO") == "hello"
        # Whitespace
        assert normalize_for_duplicate_matching("  two   words  ") == "two words"

    # --- Parenthetical suffix stripping ---

    def test_strip_remastered(self):
        assert normalize_for_duplicate_matching("Hey Jude (Remastered 2009)") == "hey jude"
        assert normalize_for_duplicate_matching("Hey Jude [Remastered]") == "hey jude"
        assert normalize_for_duplicate_matching("Hey Jude (2015 Remaster)") == "hey jude"

    def test_strip_deluxe(self):
        assert normalize_for_duplicate_matching("Abbey Road (Deluxe Edition)") == "abbey road"
        assert normalize_for_duplicate_matching("Abbey Road [Super Deluxe]") == "abbey road"

    def test_strip_expanded(self):
        assert normalize_for_duplicate_matching("OK Computer (Expanded Edition)") == "ok computer"

    def test_strip_special_edition(self):
        assert normalize_for_duplicate_matching("Dark Side (Special Edition)") == "dark side"

    def test_strip_anniversary(self):
        assert normalize_for_duplicate_matching("Thriller (25th Anniversary)") == "thriller"

    def test_strip_collector(self):
        assert normalize_for_duplicate_matching("Nevermind (Collector's Edition)") == "nevermind"

    def test_strip_bonus_track(self):
        assert normalize_for_duplicate_matching("Rumours (Bonus Track Version)") == "rumours"
        assert normalize_for_duplicate_matching("Rumours [Bonus Tracks]") == "rumours"

    def test_strip_version(self):
        assert normalize_for_duplicate_matching("Song (Acoustic Version)") == "song"

    def test_strip_feat(self):
        assert normalize_for_duplicate_matching("Song (feat. Artist)") == "song"
        assert normalize_for_duplicate_matching("Song (ft. Artist)") == "song"
        assert normalize_for_duplicate_matching("Song [featuring Artist]") == "song"

    def test_strip_remix(self):
        assert normalize_for_duplicate_matching("Song (Club Remix)") == "song"

    def test_strip_edit(self):
        assert normalize_for_duplicate_matching("Song (Radio Edit)") == "song"

    def test_strip_mono_stereo(self):
        assert normalize_for_duplicate_matching("Song (Mono)") == "song"
        assert normalize_for_duplicate_matching("Song (Stereo)") == "song"

    def test_strip_live_at(self):
        assert normalize_for_duplicate_matching("Song (Live at Wembley)") == "song"

    def test_multiple_parentheticals(self):
        assert normalize_for_duplicate_matching(
            "Song (Remastered) [Deluxe Edition]"
        ) == "song"

    def test_preserves_non_keyword_parens(self):
        # Parenthetical text without keywords should be preserved
        assert normalize_for_duplicate_matching("Song (Part 2)") == "song (part 2)"
        assert normalize_for_duplicate_matching("Song [Instrumental]") == "song [instrumental]"

    # --- Article stripping ---

    def test_strip_articles_the(self):
        assert normalize_for_duplicate_matching("The Beatles", strip_articles=True) == "beatles"

    def test_strip_articles_a(self):
        assert normalize_for_duplicate_matching("A Perfect Circle", strip_articles=True) == "perfect circle"

    def test_strip_articles_an(self):
        assert normalize_for_duplicate_matching("An Albatross", strip_articles=True) == "albatross"

    def test_no_strip_articles_by_default(self):
        assert normalize_for_duplicate_matching("The Beatles") == "the beatles"

    def test_strip_articles_case_insensitive(self):
        assert normalize_for_duplicate_matching("THE BEATLES", strip_articles=True) == "beatles"

    def test_article_not_stripped_mid_word(self):
        # "Therapy?" shouldn't lose "the" since it's not a leading article
        assert normalize_for_duplicate_matching("Therapy", strip_articles=True) == "therapy"

    # --- Real-world matching scenarios ---

    def test_remaster_variants_match(self):
        """Different remaster tags should normalize to the same string."""
        base = normalize_for_duplicate_matching("Come Together")
        assert normalize_for_duplicate_matching("Come Together (Remastered 2009)") == base
        assert normalize_for_duplicate_matching("Come Together [2015 Remaster]") == base
        assert normalize_for_duplicate_matching("Come Together (Remastered)") == base

    def test_artist_article_variants_match(self):
        """The Beatles and Beatles should match with strip_articles."""
        assert normalize_for_duplicate_matching(
            "The Beatles", strip_articles=True
        ) == normalize_for_duplicate_matching("Beatles", strip_articles=True)

    def test_album_deluxe_variants_match(self):
        """Album with/without deluxe tag should match."""
        base = normalize_for_duplicate_matching("Abbey Road")
        assert normalize_for_duplicate_matching("Abbey Road (Deluxe Edition)") == base
        assert normalize_for_duplicate_matching("Abbey Road [Super Deluxe]") == base

    def test_combined_diacritics_and_remaster(self):
        """Diacritics + remaster tag should normalize correctly."""
        assert normalize_for_duplicate_matching(
            "Björk - Homogenic (Remastered)"
        ) == "bjork - homogenic"

    # --- Dash-prefixed suffix stripping (Spotify style) ---

    def test_dash_remastered_with_year(self):
        assert normalize_for_duplicate_matching("Hey Jude - Remastered 2009") == "hey jude"

    def test_dash_radio_edit(self):
        assert normalize_for_duplicate_matching("Song - Radio Edit") == "song"

    def test_dash_remaster_with_year(self):
        assert normalize_for_duplicate_matching("Song - 2015 Remaster") == "song"

    def test_dash_preserves_non_suffix(self):
        """Non-suffix dashes should be preserved."""
        assert normalize_for_duplicate_matching("Rock - Roll") == "rock - roll"
