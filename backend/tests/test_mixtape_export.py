"""Tests for the Mix Tape Export pipeline.

The full pipeline shells out to ffmpeg, so we cover both pure-Python helpers
(filter graph, segment offsets, cover collage, tracklist text, tag round-trip)
and a real end-to-end render against synthesized inputs.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from mutagen.id3 import ID3
from PIL import Image

from app.services.mixtape_export import (
    MAX_TRACKS,
    MIN_TRACKS,
    _build_filter_graph,
    _grid_dim_for,
    _safe_name,
    _segment_offsets,
    bundle_zip,
    embed_tags,
    generate_cover,
    render_audio,
    write_tracklist,
)


def _make_track(file_path: str, idx: int) -> SimpleNamespace:
    """Stand-in for an ORM Track row — duck-typed for the export pipeline."""
    return SimpleNamespace(
        id=uuid4(),
        file_path=file_path,
        duration_seconds=3.0,
        artist=f"Artist {idx}",
        title=f"Title {idx}",
        album=f"Album {idx}",
    )


@pytest.fixture
def synth_tracks(tmp_path: Path) -> list[SimpleNamespace]:
    """Three short MP3s synthesized via ffmpeg lavfi sine generators."""
    tracks = []
    freqs = [440, 523, 659]
    for i, freq in enumerate(freqs):
        path = tmp_path / f"track_{i}.mp3"
        result = subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=3",
                "-c:a", "libmp3lame", "-b:a", "128k", str(path),
            ],
            capture_output=True,
        )
        assert result.returncode == 0, f"Failed to synth track {i}: {result.stderr!r}"
        tracks.append(_make_track(str(path), i))
    return tracks


# ── Pure helpers ────────────────────────────────────────────────────────────


class TestSegmentOffsets:
    def test_no_crossfade_concatenates(self) -> None:
        offsets = _segment_offsets([180.0, 200.0, 220.0], None)
        assert offsets == [0.0, 180.0, 380.0]

    def test_crossfade_overlaps_each_transition(self) -> None:
        offsets = _segment_offsets([180.0, 200.0, 220.0], 5)
        assert offsets == [0.0, 175.0, 370.0]

    def test_zero_crossfade_treated_as_none(self) -> None:
        assert _segment_offsets([10.0, 20.0], 0) == _segment_offsets([10.0, 20.0], None)


class TestFilterGraph:
    def test_concat_for_no_crossfade(self) -> None:
        graph = _build_filter_graph(3, None)
        assert "concat=n=3:v=0:a=1" in graph
        assert "acrossfade" not in graph
        assert "lowpass=f=15000" in graph

    def test_pairwise_crossfade_chain(self) -> None:
        graph = _build_filter_graph(4, 5)
        # 3 transitions for 4 tracks
        assert graph.count("acrossfade") == 3
        assert "c1=qsin:c2=qsin" in graph
        assert "[mix]lowpass=f=15000[out]" in graph

    def test_each_input_normalized_to_target_rate(self) -> None:
        graph = _build_filter_graph(2, None)
        # Both inputs get aresample to 44100
        assert graph.count("aresample=44100") == 2


class TestGridDim:
    def test_single_track_full_bleed(self) -> None:
        assert _grid_dim_for(1) == 1

    def test_two_to_four_tracks_2x2(self) -> None:
        for n in (2, 3, 4):
            assert _grid_dim_for(n) == 2

    def test_five_to_nine_tracks_3x3(self) -> None:
        for n in (5, 7, 9):
            assert _grid_dim_for(n) == 3

    def test_ten_to_fifteen_tracks_4x4(self) -> None:
        for n in (10, 13, 15):
            assert _grid_dim_for(n) == 4


def test_safe_name_strips_unsafe_chars() -> None:
    assert _safe_name("Hello/World") == "Hello_World"
    assert _safe_name("  Trim Me  ") == "Trim Me"
    assert _safe_name("") == "Mixtape"  # empty falls back to default


# ── Cover / tracklist (pure Pillow + text) ─────────────────────────────────


class TestGenerateCover:
    def test_outputs_correct_size_jpeg(self, tmp_path: Path) -> None:
        tracks = [_make_track("/nonexistent.mp3", i) for i in range(3)]
        out = tmp_path / "cover.jpg"
        generate_cover(tracks, "Test Mix", out)
        with Image.open(out) as img:
            assert img.format == "JPEG"
            assert img.size == (1000, 1000)

    def test_handles_missing_artwork_with_fallback_tiles(self, tmp_path: Path) -> None:
        # No real artwork on disk — should still produce a valid image.
        tracks = [_make_track("/nope.mp3", i) for i in range(8)]
        out = tmp_path / "cover.jpg"
        generate_cover(tracks, "Mix", out)
        assert out.stat().st_size > 5000  # non-trivial JPEG

    def test_byline_produces_distinct_image(self, tmp_path: Path) -> None:
        # The byline draws extra text → file should differ from the no-byline render.
        tracks = [_make_track("/nope.mp3", i) for i in range(3)]
        with_byline = tmp_path / "with.jpg"
        without_byline = tmp_path / "without.jpg"
        generate_cover(tracks, "Mix", without_byline)
        generate_cover(tracks, "Mix", with_byline, byline="Jeff")
        with Image.open(with_byline) as img:
            assert img.size == (1000, 1000)
        assert with_byline.read_bytes() != without_byline.read_bytes()


class TestWriteTracklist:
    def test_includes_offsets_and_total(self, tmp_path: Path) -> None:
        tracks = [_make_track("/x.mp3", i) for i in range(3)]
        out = tmp_path / "list.txt"
        write_tracklist(tracks, "My Mix", [0.0, 175.0, 370.0], 565.0, out)
        text = out.read_text()
        assert "My Mix" in text
        assert "01. [00:00] Artist 0 — Title 0" in text
        assert "02. [02:55] Artist 1 — Title 1" in text
        assert "03. [06:10] Artist 2 — Title 2" in text
        assert "Total duration: 09:25" in text
        # No byline line by default.
        assert "Compiled by" not in text

    def test_byline_appears_in_header(self, tmp_path: Path) -> None:
        tracks = [_make_track("/x.mp3", i) for i in range(2)]
        out = tmp_path / "list.txt"
        write_tracklist(tracks, "Mix", [0.0, 60.0], 120.0, out, byline="Jeff")
        text = out.read_text()
        assert "Compiled by Jeff" in text


# ── Render (real ffmpeg) ────────────────────────────────────────────────────


class TestRenderAudio:
    def test_concat_render_produces_expected_duration(
        self, synth_tracks: list[SimpleNamespace], tmp_path: Path
    ) -> None:
        out = tmp_path / "render.mp3"
        result = render_audio(synth_tracks, crossfade_seconds=None, output_path=out)
        assert out.is_file()
        assert result.total_duration == pytest.approx(9.0, abs=0.2)
        assert result.segment_offsets == [0.0, 3.0, 6.0]

    def test_crossfade_shortens_total_duration(
        self, synth_tracks: list[SimpleNamespace], tmp_path: Path
    ) -> None:
        out = tmp_path / "render.mp3"
        result = render_audio(synth_tracks, crossfade_seconds=1, output_path=out)
        # 3 + 3 + 3 - 2*1 = 7s
        assert result.total_duration == pytest.approx(7.0, abs=0.2)

    def test_missing_source_file_raises(self, tmp_path: Path) -> None:
        bad_track = _make_track(str(tmp_path / "nope.mp3"), 0)
        with pytest.raises(RuntimeError, match="Source file missing"):
            render_audio([bad_track, bad_track], None, tmp_path / "out.mp3")


# ── Tag embedding round-trip ────────────────────────────────────────────────


class TestEmbedTags:
    def test_round_trip_writes_all_frames(
        self, synth_tracks: list[SimpleNamespace], tmp_path: Path
    ) -> None:
        out = tmp_path / "render.mp3"
        result = render_audio(synth_tracks, crossfade_seconds=None, output_path=out)

        cover = tmp_path / "cover.jpg"
        generate_cover(synth_tracks, "Mix Tape", cover)

        embed_tags(out, "Mix Tape", cover, synth_tracks, result.segment_offsets, result.total_duration)

        tags = ID3(out)
        assert [str(f) for f in tags.getall("TIT2")] == ["Mix Tape"]
        assert [str(f) for f in tags.getall("TPE1")] == ["Various Artists"]
        assert [str(f) for f in tags.getall("TALB")] == ["Mix Tape"]
        assert [str(f) for f in tags.getall("TCON")] == ["Mixtape"]
        assert len(tags.getall("APIC")) == 1
        assert tags.getall("APIC")[0].mime == "image/jpeg"
        # One CHAP per source track + one CTOC
        assert len(tags.getall("CHAP")) == len(synth_tracks)
        assert len(tags.getall("CTOC")) == 1
        # No byline given → no TPE2/TPE4
        assert tags.getall("TPE2") == []
        assert tags.getall("TPE4") == []

    def test_byline_writes_tpe2_and_tpe4(
        self, synth_tracks: list[SimpleNamespace], tmp_path: Path
    ) -> None:
        out = tmp_path / "render.mp3"
        result = render_audio(synth_tracks, crossfade_seconds=None, output_path=out)
        cover = tmp_path / "cover.jpg"
        generate_cover(synth_tracks, "Mix Tape", cover, byline="Jeff")
        embed_tags(
            out,
            "Mix Tape",
            cover,
            synth_tracks,
            result.segment_offsets,
            result.total_duration,
            byline="Jeff",
        )
        tags = ID3(out)
        assert [str(f) for f in tags.getall("TPE2")] == ["Jeff"]
        assert [str(f) for f in tags.getall("TPE4")] == ["Jeff"]
        # TPE1 still tracks the varied source artists banner
        assert [str(f) for f in tags.getall("TPE1")] == ["Various Artists"]

    def test_byline_re_run_does_not_duplicate_frames(
        self, synth_tracks: list[SimpleNamespace], tmp_path: Path
    ) -> None:
        # Embedding tags twice (e.g., re-render) shouldn't accumulate frames.
        out = tmp_path / "render.mp3"
        result = render_audio(synth_tracks, crossfade_seconds=None, output_path=out)
        cover = tmp_path / "cover.jpg"
        generate_cover(synth_tracks, "Mix", cover)
        embed_tags(out, "Mix", cover, synth_tracks, result.segment_offsets, result.total_duration, byline="A")
        embed_tags(out, "Mix", cover, synth_tracks, result.segment_offsets, result.total_duration, byline="B")
        tags = ID3(out)
        assert [str(f) for f in tags.getall("TPE2")] == ["B"]
        assert [str(f) for f in tags.getall("TPE4")] == ["B"]


# ── Bundle ─────────────────────────────────────────────────────────────────


def test_bundle_zip_contains_all_three_artifacts(tmp_path: Path) -> None:
    audio = tmp_path / "a.mp3"
    cover = tmp_path / "cover.jpg"
    tracklist = tmp_path / "tracklist.txt"
    audio.write_bytes(b"fake mp3")
    Image.new("RGB", (100, 100), "red").save(cover)
    tracklist.write_text("01. Test")

    bundle = tmp_path / "bundle.zip"
    bundle_zip(audio, cover, tracklist, "My Mix", bundle)

    with zipfile.ZipFile(bundle) as zf:
        names = zf.namelist()
    assert "My Mix/My Mix.mp3" in names
    assert "My Mix/cover.jpg" in names
    assert "My Mix/tracklist.txt" in names


# ── Constants sanity ───────────────────────────────────────────────────────


def test_track_caps_match_plan() -> None:
    assert MIN_TRACKS == 2
    assert MAX_TRACKS == 15
