"""Who wins between the library and the file, per tag field.

The rule in one sentence: **a field a person corrected in Familiar keeps their value; a field they
never touched follows the file.**

Before this existed the file always won. `LibraryScanner._update_track` re-reads a file's tags
whenever its hash changes and assigns title, artist, album, album_artist, the numbers, year and genre
straight across. Nothing recorded that anyone had corrected them, so re-tagging in another app,
re-encoding, or replacing a file discarded the correction — silently, and with no way to notice
except spotting the old spelling again months later.

Kept in one module because three places have to agree about it: the single-track PATCH, the bulk
editor, and the scanner. Two of those write the record and one reads it, and a rule copied into three
files is the shape that goes wrong later.
"""

from typing import Any

# The fields worth protecting: exactly those `_update_track` assigns from the file *and* a person can
# edit. Deliberately not every editable field — composer, lyrics, the sort fields and the rest are
# never touched by a rescan, so recording them would pin values against nothing and make the record
# read as though it meant more than it does.
OVERRIDABLE_TAG_FIELDS: tuple[str, ...] = (
    "title",
    "artist",
    "album",
    "album_artist",
    "track_number",
    "disc_number",
    "year",
    "genre",
)


def record(existing: dict[str, Any] | None, changes: dict[str, Any]) -> dict[str, Any]:
    """Merge an edit into the stored overrides and return the new mapping.

    `changes` is what the request actually set — already filtered by `exclude_unset`, so a field
    absent here was not part of the edit and keeps whatever it had.

    A `None` value is recorded rather than skipped: clearing a genre is a decision, and one that a
    rescan would otherwise undo by refilling it from the file.

    Returns a new dict rather than mutating: SQLAlchemy does not notice in-place changes to a JSONB
    column without `flag_modified`, and a helper that silently depends on the caller remembering that
    is a trap. Assign the result.
    """
    merged = dict(existing or {})
    for field, value in changes.items():
        if field in OVERRIDABLE_TAG_FIELDS:
            merged[field] = value
    return merged


def forget(existing: dict[str, Any] | None, fields: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Drop fields from the record, so they follow the file again.

    **An undo is a retraction, not a new opinion** (ADR-0051 point 7). Undoing an accepted proposed
    change puts the old value back, and recording *that* as an override would pin the field to a
    value nobody chose — the first accepted suggestion would freeze it forever and the undo would be
    a lie.

    This is currently the only way a field stops being overridden, which ADR-0051 point 8 states
    outright rather than leaving to be discovered.
    """
    remaining = dict(existing or {})
    for field in fields:
        remaining.pop(field, None)
    return remaining


def apply(track: Any, overrides: dict[str, Any] | None) -> list[str]:
    """Put a person's corrections back on a track after its tags were re-read from the file.

    Returns the fields that were actually restored, which is what makes this observable in a log and
    testable without a database.

    Unknown keys are ignored rather than trusted: the column is JSONB and has been through a restore
    from backup, so a key that is no longer a column is a real possibility and not a reason to fail a
    library scan.
    """
    if not overrides:
        return []

    restored: list[str] = []
    for field, value in overrides.items():
        if field in OVERRIDABLE_TAG_FIELDS and hasattr(track, field):
            setattr(track, field, value)
            restored.append(field)
    return restored
