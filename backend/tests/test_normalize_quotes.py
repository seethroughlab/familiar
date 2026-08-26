"""Curly quotes fold to their ASCII forms.

**They did not, and the comment said they did.** Both character classes in
``normalize_for_matching`` held their ASCII form twice — someone typed the curly pair in
the comment and plain ones in the pattern — so U+2018/U+2019 and U+201C/U+201D passed
through untouched.

That matters because this function feeds ``compute_album_hash``: an album tagged
"Don't Stop" with a typographic apostrophe hashed differently from the same album typed
with a plain one, and got a second artwork slot. 16 albums and 30 tracks on the live
library carry a curly apostrophe.

Written with explicit escapes rather than literal characters, because the whole defect
was that ``'`` and ``’`` look alike in a monospace font.
"""

from app.services.normalize import normalize_for_matching


class TestQuotesFold:
    def test_a_typographic_apostrophe_matches_a_plain_one(self) -> None:
        assert normalize_for_matching("Don’t Stop") == normalize_for_matching("Don't Stop")

    def test_a_left_single_quote_folds_too(self) -> None:
        assert normalize_for_matching("‘Heroes’") == normalize_for_matching("'Heroes'")

    def test_typographic_double_quotes_match_plain_ones(self) -> None:
        assert normalize_for_matching("“Heroes”") == normalize_for_matching('"Heroes"')

    def test_guillemets_fold_to_double_quotes(self) -> None:
        assert normalize_for_matching("«Heroes»") == normalize_for_matching('"Heroes"')

    def test_prime_and_acute_still_fold(self) -> None:
        """The characters that already worked keep working."""
        assert normalize_for_matching("Don′t") == normalize_for_matching("Don't")
        assert normalize_for_matching("Don´t") == normalize_for_matching("Don't")


class TestTheRestIsUnchanged:
    """Guards against a fix to one class quietly breaking another."""

    def test_dashes_fold(self) -> None:
        assert normalize_for_matching("Rock — Roll") == normalize_for_matching("Rock - Roll")

    def test_diacritics_are_stripped(self) -> None:
        assert normalize_for_matching("Björk") == normalize_for_matching("Bjork")

    def test_case_and_whitespace_fold(self) -> None:
        assert normalize_for_matching("  THE   Wall ") == normalize_for_matching("the wall")

    def test_blank_input_is_empty(self) -> None:
        assert normalize_for_matching(None) == ""
        assert normalize_for_matching("   ") == ""
