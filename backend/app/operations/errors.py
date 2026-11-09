"""What an operation can fail with, independent of any transport (ADR-0173).

Operations may not import `app.api` (`scripts/lint_boundaries.py`, rule 1), so these are not the
HTTP errors in `app/api/exceptions.py`. Each adapter says what one means to its caller: the REST
routes raise the matching `NotFoundError` with its `code`; the LLM handlers return a sentence the
model can act on.
"""


class OperationError(Exception):
    """Base for failures an operation reports to its caller."""


class PlaylistNotFound(OperationError):
    """No such playlist, or not this profile's: the two are deliberately indistinguishable."""


class TrackNotFound(OperationError):
    """No such track in the library."""
