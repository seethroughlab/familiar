"""Custom exception hierarchy for the Familiar API.

These exceptions provide structured error handling with proper HTTP status codes
and consistent error response formats.
"""

from typing import Any


class FamiliarError(Exception):
    """Base exception for all Familiar errors."""

    status_code: int = 500
    message: str = "An unexpected error occurred"

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


class AnalysisInProgressError(ConflictError):
    """Audio analysis is already running."""

    message = "Audio analysis is already in progress"


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


class SpotifyAPIError(ExternalServiceError):
    """Spotify API call failed."""

    message = "Spotify request failed"


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
    import anthropic

    # Handle our custom exceptions - use their message
    if isinstance(exception, FamiliarError):
        return exception.message

    # Handle Anthropic API errors with user-friendly messages
    if isinstance(exception, anthropic.AuthenticationError):
        return "Invalid API key. Check your Anthropic API key in Settings."

    if isinstance(exception, anthropic.RateLimitError):
        return "Rate limit exceeded. Please wait a moment and try again."

    if isinstance(exception, anthropic.BadRequestError):
        return "The request could not be processed. Please try rephrasing."

    if isinstance(exception, anthropic.APIConnectionError):
        return "Could not connect to the AI service. Check your internet connection."

    if isinstance(exception, anthropic.APIStatusError):
        return "The AI service is temporarily unavailable. Please try again later."

    if isinstance(exception, anthropic.APITimeoutError):
        return "The AI request timed out. Please try again."

    if isinstance(exception, anthropic.APIError):
        return "An error occurred with the AI service. Please try again."

    # Handle common Python exceptions
    if isinstance(exception, TimeoutError):
        return "The request timed out. Please try again."

    if isinstance(exception, ConnectionError):
        return "Connection error. Check your internet connection."

    # Default - don't expose internal details
    return default_message
