"""A stored fingerprint is read back as chromaprint produced it.

`track_analysis.acoustid` is a `text` column that once held `bytea`, so it carries
the same fingerprint two ways: 14,284 rows as `\\x` plus hex, 11,364 as the base64
string itself (measured 2026-09-10). Decode the first and you get the second.

This rule began as the corpus key's canonical form (clapback's `ADR-0010`, Familiar's
`ADR-0114`). The corpus went with ADR-0159; the recording backfill (ADR-0115) still
sends stored fingerprints to AcoustID, which needs the base64 form.

Free of `numpy`, `librosa` and the ONNX artifacts, like the rest of the suite that
touches this path.
"""

from __future__ import annotations

from app.services.analysis import canonical_fingerprint

#: A real-shaped chromaprint fingerprint: base64 alphabet, begins `AQAD`.
RAW = "AQADtJESbVkUhYL84z4CnwZ4HsdxHD6P4_hx_EAO_cjx"

#: The same value as Postgres renders it after a `bytea` → `text` migration.
ESCAPED = "\\x" + RAW.encode().hex()


class TestTheTwoEncodingsAreOneFingerprint:
    def test_the_escaped_form_decodes_to_the_raw_one(self):
        """The premise. If this fails, the rest of the file measures nothing."""
        assert bytes.fromhex(ESCAPED[2:]).decode() == RAW

    def test_the_escaped_form_is_read_back_raw(self):
        assert canonical_fingerprint(ESCAPED) == RAW.encode()

    def test_the_raw_form_is_unchanged(self):
        """The 11,364 rows already stored raw must come back exactly as stored."""
        assert canonical_fingerprint(RAW) == RAW.encode()

    def test_bytes_and_str_agree(self):
        """`acoustid.fingerprint_file` returns bytes on some paths and str on others."""
        assert canonical_fingerprint(RAW.encode()) == canonical_fingerprint(RAW)


class TestTheDecodeCannotMisfire:
    def test_a_fingerprint_never_looks_like_an_encoding(self):
        """Base64 has no backslash, which is what makes the narrow rule safe."""
        assert not RAW.startswith("\\x")

    def test_unrecognised_shapes_pass_through(self):
        """Guessing would be worse than not trying: a wrong guess sends AcoustID a
        fingerprint wrong in a new way, and nothing downstream could tell."""
        for odd in ("\\xZZZZ", "\\x41514", "\\x", "not a fingerprint", ""):
            assert canonical_fingerprint(odd) == odd.encode()

    def test_hex_that_decodes_to_binary_is_not_a_fingerprint(self):
        """`\\x00ff` is well-formed hex, so only the printable-ASCII test
        separates it from an escaped fingerprint."""
        assert canonical_fingerprint("\\x00ff") == b"\\x00ff"
