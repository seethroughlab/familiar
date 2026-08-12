"""A correction made in Familiar survives the file changing underneath it.

`LibraryScanner._update_track` assigns title, artist, album, album_artist, the numbers, year and
genre straight from the file whenever its hash changes — re-tagged in another app, re-encoded,
replaced. Until `metadata_overrides` existed that silently restored the old value, and the only way
to notice was spotting the old spelling again weeks later.

These are unit tests over the rule itself rather than over a scan. `_update_track` runs deep inside a
traversal of a real directory; the rule is the part worth pinning, and it is pure.
"""

from types import SimpleNamespace

from app.services import metadata_overrides


class _Track(SimpleNamespace):
    """Enough of a Track to set attributes on."""


def _track(**kwargs: object) -> _Track:
    base = dict(
        title=None, artist=None, album=None, album_artist=None,
        track_number=None, disc_number=None, year=None, genre=None,
    )
    base.update(kwargs)
    return _Track(**base)


class TestRecording:
    def test_an_edited_field_is_remembered(self) -> None:
        assert metadata_overrides.record({}, {"album": "Selenography"}) == {"album": "Selenography"}

    def test_clearing_is_remembered_as_a_decision(self) -> None:
        """A null entry is present, not absent — otherwise a rescan refills the field it emptied."""
        recorded = metadata_overrides.record({}, {"genre": None})
        assert "genre" in recorded
        assert recorded["genre"] is None

    def test_fields_a_rescan_never_touches_are_not_recorded(self) -> None:
        """`_update_track` does not assign composer or lyrics, so pinning them would claim a
        protection that means nothing."""
        assert metadata_overrides.record({}, {"composer": "Reich", "lyrics": "…"}) == {}

    def test_earlier_edits_survive_a_later_one(self) -> None:
        first = metadata_overrides.record({}, {"album": "Selenography"})
        second = metadata_overrides.record(first, {"year": 1999})
        assert second == {"album": "Selenography", "year": 1999}

    def test_a_later_edit_wins_over_an_earlier_one(self) -> None:
        first = metadata_overrides.record({}, {"album": "Selenograpy"})
        assert metadata_overrides.record(first, {"album": "Selenography"})["album"] == "Selenography"

    def test_the_original_mapping_is_not_mutated(self) -> None:
        """SQLAlchemy does not notice in-place changes to JSONB, so the helper must return a new
        dict and the caller must assign it. A mutating helper would appear to work and persist
        nothing."""
        original = {"album": "Selenography"}
        metadata_overrides.record(original, {"year": 1999})
        assert original == {"album": "Selenography"}


class TestApplying:
    def test_an_edited_field_beats_the_file(self) -> None:
        track = _track(album="Selenograpy")  # what the file now says
        restored = metadata_overrides.apply(track, {"album": "Selenography"})
        assert track.album == "Selenography"
        assert restored == ["album"]

    def test_an_untouched_field_still_follows_the_file(self) -> None:
        track = _track(album="Selenography", artist="Rachel's")
        metadata_overrides.apply(track, {"album": "Selenography"})
        assert track.artist == "Rachel's"

    def test_a_cleared_field_stays_cleared(self) -> None:
        """The case a naive implementation gets wrong: the file has a genre, the person removed it,
        and a truthiness check would let the file put it back."""
        track = _track(genre="Post-Rock")
        metadata_overrides.apply(track, {"genre": None})
        assert track.genre is None

    def test_nothing_recorded_changes_nothing(self) -> None:
        track = _track(album="Selenography")
        assert metadata_overrides.apply(track, {}) == []
        assert metadata_overrides.apply(track, None) == []
        assert track.album == "Selenography"

    def test_unknown_keys_are_ignored_rather_than_trusted(self) -> None:
        """The column is JSONB and survives a restore from backup, so a key that is no longer a
        column is possible and is not a reason to fail a library scan."""
        track = _track()
        assert metadata_overrides.apply(track, {"not_a_column": "x"}) == []

    def test_a_field_outside_the_protected_set_is_not_applied(self) -> None:
        track = _track()
        track.composer = "Reich"
        metadata_overrides.apply(track, {"composer": "Glass"})
        assert track.composer == "Reich"


class TestTheScannerUsesIt:
    def test_update_track_reapplies_overrides_after_reading_the_file(self) -> None:
        """Asserted against the source: `_update_track` has no seam to call, and the ordering is the
        whole point — the overrides must land *after* the assignments from file tags, or the file
        wins anyway."""
        from pathlib import Path

        from app.services import scanner

        source = Path(scanner.__file__).read_text()
        body = source.split("async def _update_track", 1)[1]
        assert "metadata_overrides.apply(track, track.metadata_overrides)" in body

        assignments = body.index('track.title = metadata.get("title")')
        restore = body.index("metadata_overrides.apply(track, track.metadata_overrides)")
        assert restore > assignments, (
            "overrides are applied before the file's tags are assigned, so the file wins and the "
            "edit is lost — the bug this exists to prevent"
        )
