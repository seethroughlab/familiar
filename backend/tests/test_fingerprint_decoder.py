"""Every fingerprint is decoded the way the Docker image decodes it.

The community cache keys on the fingerprint's hash (ADR-0114), and the decoder is part of the
fingerprint: over 21 files from the NAS library, a Mac agreed with the image on 20 when the ffmpeg
command decoded the audio and on 11 when CoreAudio did, which is audioread's default on a Mac. So the
child that fingerprints names its decoders, and identification fingerprints through the same child.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import acoustid
import pytest

import app.services.analysis as analysis

FIXTURE = Path(__file__).parent / "fixtures" / "audio" / "electronic_short.mp3"

#: Prepended to the child: any use of audioread's own choice of decoder fails the run.
_NO_DEFAULT_DECODERS = """
import audioread
def _refuse(*args, **kwargs):
    raise SystemExit("the child asked audioread to choose a decoder")
audioread.available_backends = _refuse
"""


def _library_available() -> bool:
    probe = analysis._IMPORT_ACOUSTID + "sys.exit(0 if acoustid.have_chromaprint and acoustid.have_audioread else 1)\n"
    return subprocess.run([sys.executable, "-c", probe], capture_output=True).returncode == 0


@pytest.mark.skipif(not _library_available(), reason="libchromaprint is not loadable here")
def test_the_child_names_its_decoders():
    result = subprocess.run(
        [sys.executable, "-c", _NO_DEFAULT_DECODERS + analysis._FINGERPRINT_CHILD, str(FIXTURE)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("[")


def test_identification_fingerprints_through_the_same_child(monkeypatch):
    """`acoustid.match` would fingerprint in-process, with audioread's default decoder."""

    def refuse(*args, **kwargs):
        raise AssertionError("fingerprinted outside fingerprint_or_raise")

    monkeypatch.setattr(acoustid, "fingerprint_file", refuse)
    monkeypatch.setattr(acoustid, "match", refuse)
    monkeypatch.setattr(analysis, "get_acoustid_api_key", lambda: "key")
    monkeypatch.setattr(analysis, "fingerprint_or_raise", lambda path: (212.0, "AQADtEmUaFGS"))
    asked = {}

    def lookup(api_key, fingerprint, duration, meta, timeout=None):
        asked.update(fingerprint=fingerprint, duration=duration, timeout=timeout)
        return {
            "status": "ok",
            "results": [{"score": 0.9, "recordings": [{"id": "rec-1", "title": "T", "artists": [{"name": "A"}]}]}],
        }

    monkeypatch.setattr(acoustid, "lookup", lookup)

    candidates = analysis.lookup_acoustid_candidates(FIXTURE)
    single = analysis.lookup_acoustid(FIXTURE)

    assert asked["fingerprint"] == "AQADtEmUaFGS" and asked["duration"] == 212.0
    assert asked["timeout"], "pyacoustid's default is no timeout"
    assert candidates[0]["musicbrainz_recording_id"] == "rec-1"
    assert single["musicbrainz_recording_id"] == "rec-1"


def test_a_missing_chromaprint_is_reported_as_such(monkeypatch):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "Traceback …\nacoustid.NoBackendError")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(analysis.AcoustIDError) as raised:
        analysis.fingerprint_or_raise(FIXTURE)
    assert raised.value.error_type == "chromaprint_missing"
