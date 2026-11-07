"""LRC as it is really written, including the shapes that used to come out wrong."""

import pytest

from app.services.lyrics import parse_lrc


def _pairs(content: str) -> list[tuple[float, str]]:
    return [(round(line.time, 3), line.text) for line in parse_lrc(content)]


@pytest.mark.parametrize(
    ("tag", "seconds"),
    [
        ("[00:12.3]", 12.3),
        ("[00:12.34]", 12.34),
        # Was 15.45: every fraction was divided by 100.
        ("[00:12.345]", 12.345),
        ("[00:12:34]", 12.34),
        ("[00:12]", 12.0),
        ("[01:02.50]", 62.5),
        # Past an hour, minutes keep counting: LRC has no hours field.
        ("[75:00.00]", 4500.0),
    ],
)
def test_time_tags(tag, seconds):
    assert _pairs(f"{tag}a line") == [(seconds, "a line")]


def test_three_digit_fractions_stay_in_order():
    assert [text for _, text in _pairs("[00:12.950]first\n[00:13.100]second")] == ["first", "second"]


def test_a_line_with_several_tags_is_one_line_per_tag():
    # Was one line at the first time, with "[01:03.50]chorus" as its text.
    assert _pairs("[00:12.00][01:03.50]chorus") == [(12.0, "chorus"), (63.5, "chorus")]


def test_repeats_sort_among_their_neighbours():
    content = "[00:10.00][00:30.00]chorus\n[00:20.00]verse"
    assert [text for _, text in _pairs(content)] == ["chorus", "verse", "chorus"]


def test_positive_offset_makes_lyrics_sooner():
    assert _pairs("[offset:+500]\n[00:10.00]a") == [(9.5, "a")]


def test_negative_offset_makes_lyrics_later():
    assert _pairs("[offset:-500]\n[00:10.00]a") == [(10.5, "a")]


def test_an_offset_cannot_produce_a_negative_time():
    assert _pairs("[offset:5000]\n[00:01.00]a") == [(0.0, "a")]


def test_bom_and_crlf():
    assert _pairs("﻿[00:01.00]a\r\n[00:02.00]b\r\n") == [(1.0, "a"), (2.0, "b")]


def test_word_timing_is_removed_from_the_text():
    assert _pairs("[00:01.00]<00:01.00>one <00:01.50>two") == [(1.0, "one two")]


def test_metadata_tags_and_prose_are_not_lines():
    assert _pairs("[ar:Someone]\n[ti:Something]\nnot a timed line\n[00:01.00]a") == [(1.0, "a")]


def test_empty_timed_lines_are_gaps_not_lines():
    assert _pairs("[00:01.00]a\n[00:02.00]\n[00:03.00]b") == [(1.0, "a"), (3.0, "b")]


def test_nothing_parseable():
    assert parse_lrc("") == []
    assert parse_lrc("just some words") == []
