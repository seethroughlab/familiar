"""Common Pydantic schemas shared across route modules."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, PlainSerializer, WithJsonSchema

from app.utils.time import to_rfc3339

# A timestamp that serialises as RFC 3339 UTC rather than a bare naive ISO string.
#
# Use this instead of `datetime` on any response model. See `to_rfc3339` for why: the naive form
# Pydantic emits by default is rejected by strict decoders and silently misread as local time by
# JavaScript.
#
# `WithJsonSchema` is load-bearing. `PlainSerializer(return_type=str)` would otherwise degrade the
# schema to a plain string and throw away `format: date-time`, which is the very thing that makes
# a generated client decode these as dates.
UTCDateTime = Annotated[
    datetime,
    PlainSerializer(to_rfc3339, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]


class ErrorEnvelope(BaseModel):
    """The shape every error response takes (ADR-0007).

    Mirrors `create_error_response` in `app/main.py` exactly. Every handler funnels through it:
    validation errors, `FamiliarError` subclasses, `HTTPException`, SQLAlchemy failures and the
    catch-all 500.

    Modelled here because it was previously described nowhere. The schema documented only 200 and
    FastAPI's automatic 422 — and that 422 was actively wrong, because the validation handler is
    overridden to emit *this* shape rather than `{"detail": [...]}`. A generated client therefore
    had exactly one error model and it was the one the server never sends.

    `detail` and `request_id` are optional because they are **omitted** when absent rather than
    sent as null, so a client must treat them as missing keys and not as nullable values.
    """

    error: bool = Field(True, description="Always true; lets a client discriminate without status.")
    status_code: int = Field(..., description="Repeats the HTTP status, for logs and clients that lose it.")
    message: str = Field(..., description="Human-readable summary, safe to surface.")
    detail: str | None = Field(
        None,
        description="Extra context. Present for validation errors and, in debug builds, for 500s.",
    )
    request_id: str | None = Field(
        None,
        description="Correlates with the x-request-id response header and the server log.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": True,
                "status_code": 404,
                "message": "Track not found",
                "request_id": "5a5a551a",
            }
        }
    }


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Declare `ErrorEnvelope` for the given statuses, for a route's `responses=`.

    Used so a generated client models the real error shape. Attached wholesale at the
    `include_router` calls in `main.py`; individual routes add the statuses that are genuinely
    part of their control flow, such as the 409 a playback-session conflict returns.
    """
    return {code: {"model": ErrorEnvelope} for code in status_codes}


class CancelResponse(BaseModel):
    """Response for cancel operations."""

    status: str
    message: str
    requested: bool = True
    in_process_tasks_cancelled: int = 0
    subprocess_may_continue: bool = False
