"""Ordering for the track list, checked by compiling SQL rather than by running it.

No database needed: `apply_track_sort` builds a query, and what it built can be read off the compiled
statement. That keeps the two things worth guarding — which fields are sortable, and what happens
when one cannot be honoured — under test in a suite that runs anywhere.

Both `/tracks` and `/tracks/ids` go through this. They have to agree: `/tracks/ids` builds the queue
that `/tracks` paginates metadata for, so an order that differed between them would hand the player a
queue in one order and titles in another.
"""

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.api.routes.tracks import (
    PROFILE_SORT_FIELDS,
    SORT_FIELD_MAP,
    apply_track_sort,
)
from app.db.models import Track

PROFILE = SimpleNamespace(id=uuid4())


def compiled(sort_by: str | None, *, order: str = "asc", profile=PROFILE) -> str | None:
    query = apply_track_sort(
        select(Track.id),
        sort_by=sort_by,
        sort_order=order,
        profile=profile,
        has_feature_filter=False,
    )
    if query is None:
        return None
    return str(query.compile(compile_kwargs={"literal_binds": True}))


def test_the_two_fields_the_mac_needed_are_sortable() -> None:
    """Play count and date-added answer "what do I listen to" and "what is new here".

    Both columns existed and neither was reachable from any client, including the web.
    """
    assert "playCount" in SORT_FIELD_MAP
    assert "dateAdded" in SORT_FIELD_MAP

    assert "play_count" in (compiled("playCount") or "")
    assert "created_at" in (compiled("dateAdded") or "")


def test_a_play_history_sort_joins_the_listeners_own_rows() -> None:
    sql = compiled("playCount") or ""
    assert "JOIN profile_play_history" in sql
    # Scoped to one listener rather than joined on the track alone — otherwise the ordering would
    # be by *everyone's* plays, which is a different and much less useful question.
    assert "profile_play_history.profile_id" in sql


def test_a_play_history_sort_without_a_profile_is_declined() -> None:
    """"How often have you played this" has no answer when there is no you.

    Ordering by the column anyway would leave SQLAlchemy to invent a cross join against every row of
    `profile_play_history` — a wrong answer served slowly, rather than an error. Declining lets the
    caller fall back to its own default order.
    """
    for field in sorted(PROFILE_SORT_FIELDS):
        assert compiled(field, profile=None) is None, f"{field} must decline without a profile"

    # A track-owned field is unaffected by having no profile.
    assert compiled("artist", profile=None) is not None


def test_unknown_and_missing_fields_are_declined_rather_than_guessed() -> None:
    assert compiled(None) is None
    assert compiled("") is None
    assert compiled("nonsense") is None
    assert compiled("DROP TABLE tracks") is None


def test_every_sort_ends_in_a_unique_total_order() -> None:
    """`Track.id` last, on every path.

    Without it 866 tie groups covering 2,846 rows share an ordering key, and OFFSET paging over a
    non-unique order may repeat or skip rows between pages — silently omitting tracks from anything
    that pages the whole library.
    """
    for field in ["artist", "album", "dateAdded", "playCount", "bpm", "energy"]:
        sql = compiled(field) or ""
        assert sql, f"{field} should have produced a query"
        order_by = sql.split("ORDER BY", 1)[1]
        assert order_by.rstrip().endswith("tracks.id"), f"{field} does not end in a unique key"


def test_direction_is_honoured_on_both_kinds_of_field() -> None:
    for field in ["dateAdded", "playCount", "bpm"]:
        assert "DESC" in (compiled(field, order="desc") or "")
        ascending = compiled(field, order="asc") or ""
        first_key = ascending.split("ORDER BY", 1)[1].split(",")[0]
        assert "DESC" not in first_key


def test_nulls_sort_last_whichever_direction() -> None:
    """A track nobody has played should not lead a list ordered by play count."""
    for order in ("asc", "desc"):
        assert "NULLS LAST" in (compiled("playCount", order=order) or "")


def test_a_feature_sort_joins_the_analysis_table() -> None:
    sql = compiled("bpm") or ""
    assert "track_analysis" in sql
