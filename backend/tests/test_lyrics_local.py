"""The listener's own lyrics, read from real tagged files through mutagen (ADR-0163 point 1)."""

import shutil
import struct
from pathlib import Path

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3, SYLT, USLT, Encoding

from app.services.lyrics_local import read_local_lyrics

MP3 = Path(__file__).parent / "fixtures" / "audio" / "electronic_short.mp3"


@pytest.fixture
def mp3(tmp_path) -> Path:
    path = tmp_path / "song.mp3"
    shutil.copy(MP3, path)
    return path


@pytest.fixture
def flac(tmp_path) -> Path:
    """The smallest file mutagen accepts as FLAC: the marker and one STREAMINFO block."""
    path = tmp_path / "song.flac"
    streaminfo = struct.pack(">HH", 4096, 4096) + b"\x00" * 6 + bytes.fromhex("0ac44270") + b"\x00" * 20
    path.write_bytes(b"fLaC" + bytes([0x80]) + len(streaminfo).to_bytes(3, "big") + streaminfo)
    return path


def tag_id3(path: Path, *frames) -> None:
    tags = ID3()
    for frame in frames:
        tags.add(frame)
    tags.save(path)


def test_nothing_local():
    found = read_local_lyrics(None, None)
    assert found.synced is None and found.plain is None


def test_uslt_is_plain(mp3):
    tag_id3(mp3, USLT(encoding=Encoding.UTF8, lang="eng", desc="", text="one\ntwo"))
    found = read_local_lyrics(str(mp3), None)
    assert found.synced is None
    assert [line.text for line in found.plain.lines] == ["one", "two"]
    assert found.plain.source == "embedded"


def test_lrc_pasted_into_uslt_is_synced(mp3):
    tag_id3(mp3, USLT(encoding=Encoding.UTF8, lang="eng", desc="", text="[00:01.50]one\n[00:03.00]two"))
    found = read_local_lyrics(str(mp3), None)
    assert [(line.time, line.text) for line in found.synced.lines] == [(1.5, "one"), (3.0, "two")]


def test_sylt_in_milliseconds(mp3):
    tag_id3(mp3, SYLT(encoding=Encoding.UTF8, lang="eng", format=2, type=1, desc="",
                      text=[("two", 3000), ("one", 1500)]))
    found = read_local_lyrics(str(mp3), None)
    assert [(line.time, line.text) for line in found.synced.lines] == [(1.5, "one"), (3.0, "two")]


def test_sylt_in_mpeg_frames_is_not_read(mp3):
    # Format 1 counts frames; read as milliseconds it would put every line in the wrong place.
    tag_id3(mp3, SYLT(encoding=Encoding.UTF8, lang="eng", format=1, type=1, desc="", text=[("one", 40)]))
    assert read_local_lyrics(str(mp3), None).synced is None


def test_a_sidecar_outranks_the_tags(mp3):
    tag_id3(mp3, USLT(encoding=Encoding.UTF8, lang="eng", desc="", text="[00:09.00]from the tag"))
    mp3.with_suffix(".lrc").write_text("﻿[00:01.00]from the sidecar\r\n", encoding="utf-8")
    assert read_local_lyrics(str(mp3), None).synced.source == "sidecar"


def test_an_upper_case_sidecar(mp3):
    mp3.with_suffix(".LRC").write_text("[00:01.00]shouted", encoding="utf-8")
    assert read_local_lyrics(str(mp3), None).synced.lines[0].text == "shouted"


def test_a_sidecar_without_timestamps_is_ignored(mp3):
    mp3.with_suffix(".lrc").write_text("no timing here", encoding="utf-8")
    found = read_local_lyrics(str(mp3), None)
    assert found.synced is None and found.plain is None


def test_an_edit_outranks_everything(mp3):
    mp3.with_suffix(".lrc").write_text("[00:01.00]sidecar", encoding="utf-8")
    assert read_local_lyrics(str(mp3), "[00:02.00]edited").synced.source == "edited"


def test_an_edited_plain_text_outranks_embedded_plain(mp3):
    tag_id3(mp3, USLT(encoding=Encoding.UTF8, lang="eng", desc="", text="embedded"))
    assert read_local_lyrics(str(mp3), "edited words").plain.plain_text == "edited words"


@pytest.mark.parametrize("key", ["LYRICS", "UNSYNCEDLYRICS"])
def test_vorbis_comments(flac, key):
    audio = FLAC(flac)
    audio[key] = "[00:01.00]one"
    audio.save()
    assert read_local_lyrics(str(flac), None).synced.lines[0].text == "one"


def test_a_damaged_file_is_skipped_not_raised(tmp_path):
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"not audio at all")
    found = read_local_lyrics(str(broken), None)
    assert found.synced is None and found.plain is None


def test_a_missing_file_is_skipped(tmp_path):
    assert read_local_lyrics(str(tmp_path / "gone.flac"), "words").plain.plain_text == "words"


def test_nothing_is_written(mp3):
    tag_id3(mp3, USLT(encoding=Encoding.UTF8, lang="eng", desc="", text="one"))
    before = (mp3.read_bytes(), mp3.stat().st_mtime_ns)
    read_local_lyrics(str(mp3), None)
    assert (mp3.read_bytes(), mp3.stat().st_mtime_ns) == before
    assert sorted(p.name for p in mp3.parent.iterdir()) == ["song.mp3"]
