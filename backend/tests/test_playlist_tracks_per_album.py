"""`create_playlist_from_items(tracks_per_album=…)` can include a whole album.

The clamp's ceiling was 10. A host that asked for whole albums with `tracks_per_album=100` got
ten of Mezzanine's nineteen, and the result reported `matched_count: 10` as if that were the
album — nothing said "capped". Found 2026-09-14 while building a playlist of new arrivals; the
workaround was to bypass the tool and POST track ids directly.

These pin the ceiling, the coercion, and that the schema tells the host what the ceiling is —
the number lives in two places and a host can only read one of them.
"""

from __future__ import annotations

import pytest

from app.services.llm.handlers.playlists import MAX_TRACKS_PER_ALBUM, clamp_tracks_per_album
from app.services.llm.tools import MUSIC_TOOLS


class TestTheClamp:
    def test_a_whole_album_fits(self):
        assert clamp_tracks_per_album(24) == 24
        assert clamp_tracks_per_album(100) == 100

    def test_the_ceiling_is_the_named_constant(self):
        assert clamp_tracks_per_album(10_000) == MAX_TRACKS_PER_ALBUM
        assert MAX_TRACKS_PER_ALBUM >= 50, "a double album must fit"

    @pytest.mark.parametrize("value", [None, 0, "", "junk", object()])
    def test_missing_or_nonsense_defaults_to_three(self, value):
        assert clamp_tracks_per_album(value) == 3

    def test_strings_and_floats_are_coerced(self):
        assert clamp_tracks_per_album("7") == 7
        assert clamp_tracks_per_album(7.9) == 7

    def test_never_below_one(self):
        assert clamp_tracks_per_album(-5) == 1


class TestTheSchemaStatesTheCeiling:
    def test_description_names_the_maximum(self):
        spec = next(t for t in MUSIC_TOOLS if t["name"] == "create_playlist_from_items")
        description = spec["input_schema"]["properties"]["tracks_per_album"]["description"]
        assert f"max {MAX_TRACKS_PER_ALBUM}" in description
