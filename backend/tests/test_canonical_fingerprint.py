"""What this installation keys a contribution on.

clapback's `ADR-0010` and Familiar's `ADR-0114`. `fingerprint_hash` is half the
corpus key, and until 2026-09-10 it was SHA256 of *whatever string this column
happened to hold* rather than of the fingerprint.

`track_analysis.acoustid` is a `text` column that once held `bytea`, so it carries
the same fingerprint two ways: 14,284 rows as `\\x` plus hex, 11,364 as the base64
string itself (measured 2026-09-10). Decode the first and you get the second, but
they hash differently — so one recording reached the corpus under two keys, and
two clients holding the same music could never confirm each other.

The failure is silent, which is why these are tests rather than a comment: a wrong
key is a well-formed 64-character hex string that simply matches nothing.

Free of `numpy`, `librosa` and the ONNX artifacts, like the rest of the suite that
touches this path.
"""

from __future__ import annotations

import hashlib

from app.services.community_cache import CommunityCacheService

#: A real-shaped chromaprint fingerprint: base64 alphabet, begins `AQAD`.
RAW = "AQADtJESbVkUhYL84z4CnwZ4HsdxHD6P4_hx_EAO_cjx"

#: The same value as Postgres renders it after a `bytea` → `text` migration.
ESCAPED = "\\x" + RAW.encode().hex()


class TestTheTwoEncodingsAreOneFingerprint:
    def test_the_escaped_form_decodes_to_the_raw_one(self):
        """The premise. If this fails, the rest of the file measures nothing."""
        assert bytes.fromhex(ESCAPED[2:]).decode() == RAW

    def test_they_hash_alike(self):
        """The whole point. Before `ADR-0114` these differed, and that difference
        is what split 25,648 tracks across two keyspaces."""
        h = CommunityCacheService.hash_fingerprint
        assert h(RAW) == h(ESCAPED)


class TestTheHashIsOfTheFingerprintItself:
    def test_it_is_sha256_of_what_chromaprint_returned(self):
        """Pinned against `hashlib` rather than against this method's own output.

        A test that only compared the two encodings would still pass if both were
        canonicalised to something *else* — and re-keying the corpus is exactly
        the change that must not pass silently.
        """
        assert (
            CommunityCacheService.hash_fingerprint(RAW)
            == hashlib.sha256(RAW.encode()).hexdigest()
        )

    def test_the_raw_form_is_unchanged_by_canonicalisation(self):
        """The 11,364 rows already stored raw must keep the keys they have.

        This change corrects one half of the column and must not disturb the
        other, or it would strand rows it was not aimed at.
        """
        assert CommunityCacheService.canonical_fingerprint(RAW) == RAW.encode()

    def test_bytes_and_str_agree(self):
        """`acoustid.fingerprint_file` returns bytes on some paths and str on others."""
        h = CommunityCacheService.hash_fingerprint
        assert h(RAW.encode()) == h(RAW)


class TestTheDecodeCannotMisfire:
    def test_a_fingerprint_never_looks_like_an_encoding(self):
        """Base64 has no backslash, which is what makes the narrow rule safe."""
        assert not RAW.startswith("\\x")

    def test_unrecognised_shapes_pass_through(self):
        """Guessing would be worse than not trying: a wrong guess produces a key
        wrong in a new way, and nothing downstream could tell."""
        for odd in ("\\xZZZZ", "\\x41514", "\\x", "not a fingerprint", ""):
            assert CommunityCacheService.canonical_fingerprint(odd) == odd.encode()

    def test_hex_that_decodes_to_binary_is_not_a_fingerprint(self):
        """`\\x00ff` is well-formed hex, so only the printable-ASCII test
        separates it from an escaped fingerprint."""
        assert CommunityCacheService.canonical_fingerprint("\\x00ff") == b"\\x00ff"


class TestItAgreesWithTheOtherClient:
    def test_the_rule_matches_clapbacks_reference_implementation(self):
        """Two clients that disagree about the key cannot confirm each other, and
        the corpus cannot tell that from two people owning different recordings.

        Reproduced here rather than imported: `clapback` the CLI is not a
        dependency of this application, and the point is that two independent
        implementations of one written rule agree.
        """

        def clapback_cli_rule(value: str) -> str:
            raw = value.encode()
            if raw.startswith(b"\\x") and len(raw) % 2 == 0:
                try:
                    decoded = bytes.fromhex(raw[2:].decode("ascii"))
                except (ValueError, UnicodeDecodeError):
                    return hashlib.sha256(raw).hexdigest()
                if decoded and all(32 <= b < 127 for b in decoded):
                    return hashlib.sha256(decoded).hexdigest()
            return hashlib.sha256(raw).hexdigest()

        for case in (RAW, ESCAPED, "\\xZZ", "not a fingerprint", ""):
            assert CommunityCacheService.hash_fingerprint(case) == clapback_cli_rule(case)
