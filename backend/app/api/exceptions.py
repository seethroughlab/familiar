"""Custom exception hierarchy for the Familiar API.

These exceptions provide structured error handling with proper HTTP status codes
and consistent error response formats.
"""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Stable, machine-readable names for the errors a client acts on (ADR-0129 point 6).

    `message` and `detail` are for people and may be reworded at any time; a client that needs
    to *do* something — prompt for a token, drop a dead profile — switches on `code`. Add a member
    when a client needs to distinguish a case, not for every exception class: most errors are
    shown, not handled. Documented in `docs/ERROR-CONTRACTS.md`.
    """

    SERVER_TOKEN_REQUIRED = "SERVER_TOKEN_REQUIRED"
    INVALID_PROFILE = "INVALID_PROFILE"
    SCAN_IN_PROGRESS = "SCAN_IN_PROGRESS"
    ANALYSIS_IN_PROGRESS = "ANALYSIS_IN_PROGRESS"


class FamiliarError(Exception):
    """Base exception for all Familiar errors."""

    status_code: int = 500
    message: str = "An unexpected error occurred"
    #: Set on the subclasses a client switches on; `None` for the rest (the key is then omitted).
    code: ErrorCode | None = None

    def __init__(
        self,
        message: str | None = None,
        detail: str | None = None,
        **extra: Any,
    ) -> None:
        self.message = message or self.__class__.message
        self.detail = detail
        self.extra = extra
        super().__init__(self.message)


# 400 Bad Request errors
class ValidationError(FamiliarError):
    """Invalid input data."""

    status_code = 400
    message = "Invalid request data"


class InvalidPathError(FamiliarError):
    """Invalid file or directory path."""

    status_code = 400
    message = "Invalid path"


# 404 Not Found errors
class NotFoundError(FamiliarError):
    """Requested resource not found."""

    status_code = 404
    message = "Resource not found"


class TrackNotFoundError(NotFoundError):
    """Track not found in the library."""

    message = "Track not found"


class PlaylistNotFoundError(NotFoundError):
    """Playlist not found."""

    message = "Playlist not found"


class ProfileNotFoundError(NotFoundError):
    """Profile not found."""

    message = "Profile not found"


# 401 Unauthorized
class AuthenticationError(FamiliarError):
    """Authentication or profile identification required."""

    status_code = 401
    message = "Authentication required"


class InvalidProfileError(AuthenticationError):
    """The X-Profile-ID header names a profile that does not exist.

    Was a bare `HTTPException(401, ...)` in `deps.py`. The web client's interceptor matched its
    sentence — in the wrong envelope key, so it never fired — and clearing the dead profile is
    the one thing a client must *do* with this error, which is what `code` is for.
    """

    message = "Invalid profile ID - please re-register"
    code = ErrorCode.INVALID_PROFILE


# 413 Payload Too Large
class PayloadTooLargeError(FamiliarError):
    """Request payload exceeds size or count limits."""

    status_code = 413
    message = "Request too large"


# 422 Unprocessable Entity
class UnprocessableEntityError(FamiliarError):
    """Request is syntactically valid but cannot be processed."""

    status_code = 422
    message = "Cannot process request"


# 409 Conflict errors
class ConflictError(FamiliarError):
    """Request conflicts with current state."""

    status_code = 409
    message = "Request conflicts with current state"


class ScanInProgressError(ConflictError):
    """A library scan is already running."""

    message = "A library scan is already in progress"
    code = ErrorCode.SCAN_IN_PROGRESS


class AnalysisInProgressError(ConflictError):
    """Audio analysis is already running."""

    message = "Audio analysis is already in progress"
    code = ErrorCode.ANALYSIS_IN_PROGRESS


# 503 Service Unavailable errors
class ServiceUnavailableError(FamiliarError):
    """External service or dependency unavailable."""

    status_code = 503
    message = "Service temporarily unavailable"


class LLMNotConfiguredError(ServiceUnavailableError):
    """LLM API not configured."""

    message = "AI assistant not configured. Add your API key in the Admin panel."


class ExternalServiceError(ServiceUnavailableError):
    """External API call failed."""

    message = "External service request failed"


# 500 Internal Server errors
class DatabaseError(FamiliarError):
    """Database operation failed."""

    status_code = 500
    message = "Database operation failed"


class FileOperationError(FamiliarError):
    """File system operation failed."""

    status_code = 500
    message = "File operation failed"


class AnalysisError(FamiliarError):
    """Audio analysis failed."""

    status_code = 500
    message = "Audio analysis failed"


class MapComputationError(FamiliarError):
    """UMAP/t-SNE map computation failed."""

    status_code = 500
    message = "Failed to compute library map"




class LibraryImportError(FamiliarError):
    """Library import operation failed."""

    status_code = 500
    message = "Failed to import library data"


class TranscodeError(FamiliarError):
    """Audio transcoding failed."""

    status_code = 502
    message = "Audio transcoding failed"


def create_sse_error(
    error_code: str,
    user_message: str | None = None,
) -> str:
    """Create a sanitized SSE error event.

    Returns a JSON-encoded error dict suitable for SSE event data.
    Logs the error code for debugging while sending a safe message to clients.

    Args:
        error_code: Short error code for logging (e.g., "map_computation_failed")
        user_message: Optional user-friendly message. Defaults to generic message.

    Returns:
        JSON string with error field for SSE event data
    """
    import json
    import logging

    logger = logging.getLogger(__name__)
    logger.error(f"SSE error: {error_code}")

    message = user_message or "An unexpected error occurred. Please try again."
    return json.dumps({"error": message})


def sanitize_error_for_client(
    exception: Exception,
    default_message: str = "An unexpected error occurred",
) -> str:
    """Sanitize an exception for safe client exposure.

    Converts internal exceptions to user-friendly messages without
    exposing stack traces, file paths, or other sensitive details.

    Args:
        exception: The exception to sanitize
        default_message: Message to use for unknown exception types

    Returns:
        A user-friendly error message safe for client display
    """
    # Handle our custom exceptions - use their message
    if isinstance(exception, FamiliarError):
        return exception.message

    # **No SDK exception can reach here any more.** This block matched `anthropic.*` and
    # `openai.*` error types and named the active provider in the copy. ADR-0048 step 4 removed the
    # provider layer and both SDKs — Familiar calls no model at all, the host brings one — so those
    # branches were matching types nothing could raise, and importing two SDKs to do it.

    # Handle common Python exceptions
    if isinstance(exception, TimeoutError):
        return "The request timed out. Please try again."

    if isinstance(exception, ConnectionError):
        return "Connection error. Check your internet connection."

    # Default - don't expose internal details
    return default_message
