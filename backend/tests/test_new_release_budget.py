"""The scan must return within its budget even when MusicBrainz stalls."""
import asyncio, time, pytest
from app.api.routes.library_artists import (
    NEW_RELEASE_SCAN_BUDGET_SECONDS, NEW_RELEASE_PER_ARTIST_TIMEOUT_SECONDS,
)
from app.services.llm.handlers.discovery import _new_release_note

def test_budgets_are_sane():
    # A person is waiting; per-artist must be well inside the whole-scan budget or one stalled
    # lookup starves the rest.
    assert NEW_RELEASE_PER_ARTIST_TIMEOUT_SECONDS < NEW_RELEASE_SCAN_BUDGET_SECONDS / 2
    assert NEW_RELEASE_SCAN_BUDGET_SECONDS <= 30

def test_note_distinguishes_empty_from_unfinished():
    empty = _new_release_note(found=0, new_count=0, artists_checked=15, days_back=90,
                              partial=False, stalled=False)
    stalled = _new_release_note(found=0, new_count=0, artists_checked=3, days_back=90,
                                partial=True, stalled=True)
    assert "No recent releases" in empty
    # The bug this exists for: a rate-limited scan used to report "no recent releases", which is a
    # confident wrong answer rather than a failure.
    assert "No recent releases" not in stalled
    assert "503" in stalled or "did not answer" in stalled
    assert empty != stalled

@pytest.mark.asyncio
async def test_per_artist_timeout_actually_bounds_a_stalled_call():
    def stalls(): time.sleep(30)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.to_thread(stalls),
                               timeout=NEW_RELEASE_PER_ARTIST_TIMEOUT_SECONDS)
    assert time.monotonic() - started < NEW_RELEASE_PER_ARTIST_TIMEOUT_SECONDS + 2
