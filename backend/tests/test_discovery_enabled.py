"""Discovery can be turned off, and being off is visible (ADR-0099 point 12).

The reason this exists: discovery went from an occasional nightly job to a process
contacting MusicBrainz every twenty minutes and ListenBrainz every three hours,
about what one person listens to. That is a change in posture, and a self-hosted
music server should let its owner decline it in one place.
"""

from datetime import timedelta

import pytest

from app.services.app_settings import get_app_settings_service
from app.services.discovery import source_enabled
from app.utils.time import utcnow


@pytest.fixture
def settings_off():
    """Turn discovery off for one test, then put it back."""
    service = get_app_settings_service()
    original = {
        key: service.get_effective(key)
        for key in (
            "discovery_enabled",
            "discovery_musicbrainz_enabled",
            "discovery_listenbrainz_enabled",
        )
    }
    yield service
    for key, value in original.items():
        service.update(**{key: value})


def test_enabled_by_default():
    """Defaulting to on matters: a discovery server that discovers nothing until
    somebody finds a switch is a worse default than the posture question."""
    assert source_enabled("musicbrainz") is True
    assert source_enabled("listenbrainz") is True


def test_the_master_switch_stops_every_source(settings_off):
    settings_off.update(**{"discovery_enabled": False})
    assert source_enabled("musicbrainz") is False
    assert source_enabled("listenbrainz") is False


def test_one_source_can_be_turned_off_without_the_others(settings_off):
    """Otherwise the response to one source misbehaving is to disable discovery
    entirely — which is effectively what happened on 2026-08-30."""
    settings_off.update(**{"discovery_musicbrainz_enabled": False})
    assert source_enabled("musicbrainz") is False
    assert source_enabled("listenbrainz") is True


def test_the_job_itself_has_no_flag_of_its_own(settings_off):
    """`discovery_batch` is the job, not an upstream, so only the master switch
    governs it. A missing per-source flag must not read as "disabled"."""
    assert source_enabled("discovery_batch") is True
    settings_off.update(**{"discovery_enabled": False})
    assert source_enabled("discovery_batch") is False


# ---------------------------------------------------------------------------
# Off must not look like fine
# ---------------------------------------------------------------------------


def test_a_disabled_source_does_not_report_as_working():
    """**The load-bearing test of this change.**

    A disabled source keeps its last success forever, so without an explicit state
    it would read `working` indefinitely after being switched off — and "off" would
    be indistinguishable from "fine". That is the exact confusion this health surface
    exists to remove, reintroduced by the switch meant to give the owner control.
    """
    from app.api.routes.health import _source_state

    class _Row:
        backoff_until = None
        last_attempt_at = utcnow().replace(tzinfo=None) - timedelta(hours=1)
        last_success_at = utcnow().replace(tzinfo=None) - timedelta(hours=1)
        consecutive_failures = 0

    now = utcnow().replace(tzinfo=None)
    assert _source_state(_Row(), now, enabled=True) == "working"
    assert _source_state(_Row(), now, enabled=False) == "disabled"


def test_disabled_beats_every_other_state():
    """Including failure. A source that was failing and has since been turned off is
    off — continuing to alarm about an upstream nobody is contacting is noise."""
    from app.api.routes.health import _source_state

    class _Failing:
        backoff_until = utcnow().replace(tzinfo=None) + timedelta(minutes=5)
        last_attempt_at = utcnow().replace(tzinfo=None)
        last_success_at = None
        consecutive_failures = 9

    now = utcnow().replace(tzinfo=None)
    assert _source_state(_Failing(), now, enabled=True) == "backing_off"
    assert _source_state(_Failing(), now, enabled=False) == "disabled"
