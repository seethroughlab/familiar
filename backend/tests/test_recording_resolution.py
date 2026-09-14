"""The four tiers of ADR-0115 point 3, over the response shapes the probes saw.

Offline: every case is an AcoustID response written down, including the ones the
2026-09-14 measurement put in the refusal buckets. What must hold is that a
recording is named only when exactly one rule leaves exactly one candidate, and
that a refusal keeps what it refused.
"""

from __future__ import annotations

from app.services.recording_resolution import (
    MATCH_THRESHOLD,
    MIN_SCORE,
    candidates_as_json,
    resolve,
    similarity,
)

A = "aaaaaaaa-0000-4000-8000-000000000001"
B = "bbbbbbbb-0000-4000-8000-000000000002"
C = "cccccccc-0000-4000-8000-000000000003"


def rec(mbid, title, *groups, sources=1, artist="Someone"):
    return {
        "id": mbid,
        "title": title,
        "artists": [{"id": "x", "name": artist}],
        "releasegroups": [{"id": f"rg-{g}", "title": g} for g in groups],
        "sources": sources,
    }


def response(*recordings, score=0.97):
    return {"status": "ok", "results": [{"id": "acoustid-1", "score": score, "recordings": list(recordings)}]}


class TestTier1:
    def test_one_recording_is_named_whatever_the_title_says(self):
        r = resolve(response(rec(A, "Completely Different")), title="Sambatiki", album="X")
        assert r.resolved and r.recording_mbid == A and r.tier == 1 and r.reason == "single"

    def test_the_id_is_lower_cased(self):
        r = resolve(response(rec(A.upper(), "t")), title="t", album=None)
        assert r.recording_mbid == A


class TestTier2:
    def test_exactly_one_title_match_wins(self):
        r = resolve(
            response(rec(A, "Gantz Graf"), rec(B, "Dial.")),
            title="Gantz Graf",
            album="Gantz Graf",
        )
        assert r.recording_mbid == A and r.tier == 2

    def test_punctuation_case_and_one_token_in_five_do_not_matter(self):
        r = resolve(
            response(rec(A, "Song Against Sex (Album Version)"), rec(B, "Something Else")),
            title="song against sex - album version - edit",
            album=None,
        )
        assert r.tier == 2

    def test_a_leading_article_on_a_short_title_is_not_forgiven(self):
        """3 of 4 tokens is 0.75. The rule is what it is; it is not what a person would say."""
        r = resolve(
            response(rec(A, "The Ageing Young Rebel"), rec(B, "Something Else")),
            title="Ageing Young Rebel",
            album=None,
        )
        assert r.reason == "no_title_match"

    def test_the_measured_refusal_fenixfunk(self):
        """'Fenixfunk 5' against 'Fenix Funk 5' is the ADR's example of what is left alone."""
        r = resolve(
            response(rec(A, "Fenix Funk 5", "Confield"), rec(B, "Fenix Funk 5", "Confield")),
            title="Fenixfunk 5",
            album="Confield",
        )
        assert not r.resolved and r.reason == "no_title_match"
        assert {c.recording_mbid for c in r.candidates} == {A, B}


class TestTier3:
    def test_the_album_splits_same_title_duplicates(self):
        r = resolve(
            response(
                rec(A, "Sambatiki", "Ultra-Lounge, Vol. 15", sources=40),
                rec(B, "Sambatiki", "Capitol Collector's Series", sources=90),
            ),
            title="Sambatiki",
            album="Ultra-Lounge, Vol. 15",
        )
        assert r.recording_mbid == A and r.tier == 3


class TestTier4:
    def test_sources_decide_when_the_album_matches_several(self):
        r = resolve(
            response(
                rec(A, "Darling Nikki", "Purple Rain", sources=3551),
                rec(B, "Darling Nikki", "Purple Rain", sources=2),
            ),
            title="Darling Nikki",
            album="Purple Rain",
        )
        assert r.recording_mbid == A and r.tier == 4 and r.reason == "sources"

    def test_sources_decide_when_the_album_matches_none(self):
        """The 5% bucket: 'Hi Scores EP' against release groups that say 'Hi Scores'
        and three others. Tier 3 leaves nothing; tier 4 still has the title matches."""
        r = resolve(
            response(
                rec(A, "Nlogax", "Music Has the Right to Children", sources=641),
                rec(B, "Nlogax", "2002-02-22: Helter Skelter, Paris", sources=1),
            ),
            title="Nlogax",
            album="Hi Scores EP",
        )
        assert r.recording_mbid == A and r.tier == 4

    def test_a_tie_refuses(self):
        r = resolve(
            response(rec(A, "Birds", "X", sources=5), rec(B, "Birds", "X", sources=5)),
            title="Birds",
            album="X",
        )
        assert not r.resolved and r.reason == "tied"


class TestRefusals:
    def test_no_result(self):
        r = resolve({"status": "ok", "results": []}, title="t", album=None)
        assert r.reason == "no_result" and r.score == 0.0 and r.candidates == ()

    def test_low_score_keeps_its_candidates(self):
        r = resolve(response(rec(A, "t"), score=0.42), title="t", album=None)
        assert r.reason == "low_score" and r.candidates and not r.resolved

    def test_a_known_fingerprint_with_no_recording(self):
        r = resolve({"results": [{"id": "acoustid-1", "score": 0.99}]}, title="t", album=None)
        assert r.reason == "no_recording"

    def test_the_highest_scoring_result_is_the_one_read(self):
        data = {
            "results": [
                {"id": "lo", "score": 0.5, "recordings": [rec(C, "wrong")]},
                {"id": "hi", "score": 0.95, "recordings": [rec(A, "right")]},
            ]
        }
        assert resolve(data, title="right", album=None).recording_mbid == A

    def test_duplicate_ids_within_a_result_count_once(self):
        r = resolve(response(rec(A, "t"), rec(A, "t")), title="t", album=None)
        assert r.tier == 1


class TestTheStoredShape:
    def test_candidates_carry_what_the_identification_feature_reads(self):
        r = resolve(response(rec(A, "t", "G", sources=3, artist="Plaid")), title="t", album=None)
        (row,) = candidates_as_json(r)
        assert row["musicbrainz_recording_id"] == A
        assert row["acoustid_score"] == r.score
        assert row["title"] == "t" and row["artist"] == "Plaid"
        assert row["release_groups"] == ["G"] and row["sources"] == 3


class TestTheThresholds:
    def test_similarity_is_jaccard_over_tokens(self):
        assert similarity("Ageing Young Rebel", "The Ageing Young Rebel") == 0.75
        assert similarity("", "x") == 0.0

    def test_the_constants_are_the_adrs(self):
        assert MIN_SCORE == 0.8 and MATCH_THRESHOLD == 0.8
