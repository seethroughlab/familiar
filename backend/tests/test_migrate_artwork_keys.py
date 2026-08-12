"""The artwork re-key moves files without ever destroying one (ADR-0052).

The database half needs a real library, so these cover the filesystem half — which is
the half that can lose somebody's cover. Three properties matter:

- **the `.generated` marker travels with its images, present or absent.** Its absence is
  the only evidence that art was hand-uploaded rather than fetched, and
  `/artwork/regenerate` reads exactly that to refuse overwriting real art
- **a merge keeps the best claim and quarantines the rest.** Re-keying is a merge by
  design: 284 new keys receive more than one old one, and one album absorbs 49
- **nothing is deleted**, because an orphan may be a cover chosen for an album that has
  since been renamed
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import migrate_artwork_keys as mig  # noqa: E402


def _write(art: Path, key: str, *, size: int = 100, generated: bool = False) -> None:
    (art / f"{key}.jpg").write_bytes(b"x" * size)
    (art / f"{key}_thumb.jpg").write_bytes(b"t" * 10)
    if generated:
        (art / f"{key}.generated").write_text("4")


class TestPlanning:
    def test_keys_are_grouped_by_destination_album(self, tmp_path: Path) -> None:
        _write(tmp_path, "aaa")
        _write(tmp_path, "bbb")
        by_album, orphans = mig._plan(tmp_path, {"aaa": "album-1", "bbb": "album-1"})
        assert by_album == {"album-1": ["aaa", "bbb"]}
        assert orphans == []

    def test_a_key_nothing_claims_is_an_orphan(self, tmp_path: Path) -> None:
        _write(tmp_path, "ccc")
        by_album, orphans = mig._plan(tmp_path, {})
        assert by_album == {}
        assert orphans == ["ccc"]

    def test_temp_files_are_ignored(self, tmp_path: Path) -> None:
        """`atomic_write_via` leaves `.tmp` siblings; they are not artwork."""
        _write(tmp_path, "ddd")
        (tmp_path / "ddd.jpg.tmp").write_bytes(b"partial")
        _, orphans = mig._plan(tmp_path, {})
        assert orphans == ["ddd"]

    def test_a_marker_alone_still_counts_as_present(self, tmp_path: Path) -> None:
        """A `.generated` with no images is still state worth moving rather than
        stranding — it is what stops regeneration."""
        (tmp_path / "eee.generated").write_text("4")
        _, orphans = mig._plan(tmp_path, {})
        assert orphans == ["eee"]


class TestPrecedence:
    def test_real_art_outranks_generated(self, tmp_path: Path) -> None:
        _write(tmp_path, "real", size=10)
        _write(tmp_path, "gen", size=9999, generated=True)
        assert mig._weight(tmp_path, "real") > mig._weight(tmp_path, "gen")

    def test_between_two_real_ones_the_larger_wins(self, tmp_path: Path) -> None:
        _write(tmp_path, "small", size=10)
        _write(tmp_path, "big", size=5000)
        assert mig._weight(tmp_path, "big") > mig._weight(tmp_path, "small")


class TestMoving:
    def test_the_absence_of_a_marker_is_preserved(self, tmp_path: Path) -> None:
        """The case that matters most: hand-uploaded art must not gain a marker."""
        _write(tmp_path, "hand", generated=False)
        src, dst = mig._paths_for(tmp_path, "hand"), mig._paths_for(tmp_path, "album-1")
        for kind in ("full", "thumb", "generated"):
            mig._move(src[kind], dst[kind], dry_run=False)
        assert dst["full"].exists()
        assert not dst["generated"].exists()

    def test_a_marker_travels_with_its_images(self, tmp_path: Path) -> None:
        _write(tmp_path, "auto", generated=True)
        src, dst = mig._paths_for(tmp_path, "auto"), mig._paths_for(tmp_path, "album-2")
        for kind in ("full", "thumb", "generated"):
            mig._move(src[kind], dst[kind], dry_run=False)
        assert dst["generated"].read_text() == "4"

    def test_a_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        _write(tmp_path, "keepme")
        src, dst = mig._paths_for(tmp_path, "keepme"), mig._paths_for(tmp_path, "album-3")
        mig._move(src["full"], dst["full"], dry_run=True)
        assert src["full"].exists()
        assert not dst["full"].exists()

    def test_an_existing_destination_is_left_alone(self, tmp_path: Path) -> None:
        """Idempotence — a repeated run must not clobber what the first one placed."""
        _write(tmp_path, "src", size=10)
        (tmp_path / "album-4.jpg").write_bytes(b"already here")
        mig._move(tmp_path / "src.jpg", tmp_path / "album-4.jpg", dry_run=False)
        assert (tmp_path / "album-4.jpg").read_bytes() == b"already here"
        assert (tmp_path / "src.jpg").exists()

    def test_quarantine_moves_all_three_and_deletes_none(self, tmp_path: Path) -> None:
        _write(tmp_path, "loser", generated=True)
        mig._quarantine(tmp_path, "loser", reason="merged", dry_run=False)
        q = tmp_path / "quarantine" / "merged"
        assert {p.name for p in q.iterdir()} == {
            "loser.jpg", "loser_thumb.jpg", "loser.generated",
        }
        assert not (tmp_path / "loser.jpg").exists()
