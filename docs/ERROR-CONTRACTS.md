# Error Contracts

Canonical error handling reference for the Familiar API. Covers REST JSON, SSE streams, the exception hierarchy, and usage guidance.

---

## REST JSON Error Envelope

All REST error responses use a consistent envelope produced by `create_error_response()` in `main.py`:

```json
{
  "error": true,
  "status_code": 400,
  "message": "Human-readable message",
  "detail": "Optional technical detail (validation errors, debug info)",
  "request_id": "Optional request trace ID"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `error` | `boolean` | Yes | Always `true` for error responses |
| `status_code` | `integer` | Yes | HTTP status code (mirrors the response status) |
| `message` | `string` | Yes | User-friendly error message safe for display |
| `detail` | `string` | No | Technical detail — validation errors, debug info. Omitted in production for 500s |
| `request_id` | `string` | No | Request trace ID from `X-Request-ID` header |

---

## FamiliarError Hierarchy

All custom exceptions inherit from `FamiliarError` (defined in `app/api/exceptions.py`). The global handler in `main.py` maps each exception's `status_code` to the envelope above.

### 400 Bad Request

| Exception | Default Message | When to Use |
|-----------|-----------------|-------------|
| `ValidationError` | "Invalid request data" | Bad input, invalid format, semantic validation |
| `InvalidPathError` | "Invalid path" | File or directory path issues |

### 401 Unauthorized

| Exception | Default Message | When to Use |
|-----------|-----------------|-------------|
| `AuthenticationError` | "Authentication required" | Missing or invalid profile/auth |

### 404 Not Found

| Exception | Default Message | When to Use |
|-----------|-----------------|-------------|
| `NotFoundError` | "Resource not found" | Generic resource not found |
| `TrackNotFoundError` | "Track not found" | Track lookup failed |
| `PlaylistNotFoundError` | "Playlist not found" | Playlist lookup failed |
| `ProfileNotFoundError` | "Profile not found" | Profile lookup failed |

### 409 Conflict

| Exception | Default Message | When to Use |
|-----------|-----------------|-------------|
| `ConflictError` | "Request conflicts with current state" | State conflict |
| `ScanInProgressError` | "A library scan is already in progress" | Duplicate scan attempt |
| `AnalysisInProgressError` | "Audio analysis is already in progress" | Duplicate analysis attempt |

### 413 Payload Too Large

| Exception | Default Message | When to Use |
|-----------|-----------------|-------------|
| `PayloadTooLargeError` | "Request too large" | Upload size or count exceeded |

### 422 Unprocessable Entity

| Exception | Default Message | When to Use |
|-----------|-----------------|-------------|
| `UnprocessableEntityError` | "Cannot process request" | Syntactically valid but semantically unprocessable |

### 500 Internal Server Error

| Exception | Default Message | When to Use |
|-----------|-----------------|-------------|
| `DatabaseError` | "Database operation failed" | DB errors |
| `FileOperationError` | "File operation failed" | Filesystem errors |
| `AnalysisError` | "Audio analysis failed" | Analysis pipeline failure |
| `MapComputationError` | "Failed to compute library map" | UMAP/t-SNE failure |
| `LibraryImportError` | "Failed to import library data" | Import failure |

### 503 Service Unavailable

| Exception | Default Message | When to Use |
|-----------|-----------------|-------------|
| `ServiceUnavailableError` | "Service temporarily unavailable" | External dependency down |
| `LLMNotConfiguredError` | "AI assistant not configured..." | No API key set |
| `ExternalServiceError` | "External service request failed" | External API call failure |
| `SpotifyAPIError` | "Spotify request failed" | Spotify API failure |

---

## Status Code Decision Matrix

| Scenario | Code | Exception |
|----------|------|-----------|
| Malformed input (bad UUID, wrong type) | 422 | Pydantic `RequestValidationError` (automatic) |
| Semantically invalid input (bad value, missing field) | 400 | `ValidationError` |
| Missing profile header on protected route | 401 | `HTTPException` from `require_profile` |
| Invalid profile UUID format | 400 | `HTTPException` from deps |
| Resource not found | 404 | `*NotFoundError` subclass |
| Duplicate operation in progress | 409 | `*InProgressError` subclass |
| Request too large | 413 | `PayloadTooLargeError` |
| External service unavailable | 503 | `ServiceUnavailableError` subclass |
| Internal error | 500 | `DatabaseError`, `FileOperationError`, etc. |

---

## Global Handler Chain

Five exception handlers are registered in `main.py` (lines 257–338), processed in this priority order:

| Priority | Handler | Catches | Status | Notes |
|----------|---------|---------|--------|-------|
| 1 | `validation_exception_handler` | `RequestValidationError` | 422 | Pydantic validation failures. Joins error locations into `detail` |
| 2 | `sqlalchemy_exception_handler` | `SQLAlchemyError` | 500 | Database errors. Detail included only when `debug=True` |
| 3 | `familiar_exception_handler` | `FamiliarError` | Per exception | Uses the exception's `status_code`, `message`, and `detail` |
| 4 | `http_exception_handler` | `HTTPException` | Per exception | Normalizes Starlette/FastAPI HTTPExceptions to the standard envelope |
| 5 | `generic_exception_handler` | `Exception` | 500 | Catch-all. Detail included only when `debug=True` |

All handlers attach the `request_id` from middleware and log at appropriate levels (warning for 4xx, error for 5xx).

---

## SSE Error Contracts

Two SSE patterns exist, driven by different client consumption models.

### Chat Stream (`POST /chat/stream`)

Uses raw `data:` lines with typed JSON objects. The frontend parses via `fetch` + line splitting, switching on `event.type`.

**Error shape:**
```
data: {"type": "error", "message": "User-friendly message"}
data: [DONE]
```

Error messages are sanitized via `sanitize_error_for_client()` before sending.

### Map Streams (`GET /library/map/stream`, `/map/3d/stream`)

Uses named SSE events. The frontend parses via `EventSource` with named event listeners.

**Error shape:**
```
event: error
data: {"error": "User-friendly message"}
```

Error messages are produced via `create_sse_error()` which logs the error code and returns a sanitized JSON string.

### Why Two Formats?

Different consumption patterns justify different wire formats:
- **Chat**: Uses `fetch` (for POST support) + manual line parsing → typed JSON with `type` discriminator
- **Maps**: Uses `EventSource` (GET only) + named event listeners → `event:` prefix with simple payload

### Pre-Stream Errors

Errors raised *before* `StreamingResponse` is returned (e.g., `LLMNotConfiguredError` in chat, `ServiceUnavailableError` in maps) return the standard REST JSON envelope, not SSE. This is validated by `test_contract_envelope_parity.py`.

---

## Usage Guide

### Raising Errors in Route Handlers

Use `FamiliarError` subclasses for domain errors:

```python
from app.api.exceptions import TrackNotFoundError, ValidationError

# Simple — uses the class default message
raise TrackNotFoundError()

# Custom message
raise ValidationError("File must be a ZIP archive")

# With technical detail (shown in envelope's `detail` field)
raise ValidationError("File too large", detail=f"Max size: {max_size} MB")
```

### When to Use FamiliarError vs HTTPException

- **FamiliarError subclasses** — preferred for all domain logic. Provides typed hierarchy, consistent messages, and structured `detail`.
- **HTTPException** — only for infrastructure concerns in `deps.py` (profile validation, auth). The global handler normalizes these to the standard envelope.

### The `detail` Kwarg Pattern

Use `detail=` for technical information that helps debugging but shouldn't be the primary user-facing message:

```python
# Good: message is user-friendly, detail has technical context
raise ValidationError("Cannot import library", detail=f"Unsupported format: {fmt}")

# Bad: leaking internal info in the message
raise ValidationError(f"sqlalchemy.exc.IntegrityError: duplicate key {key}")
```

In production, 500-level `detail` fields from the catch-all handler are suppressed (only shown when `debug=True`). FamiliarError `detail` is always included since it's explicitly set by the developer.
