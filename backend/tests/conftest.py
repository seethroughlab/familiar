"""
Test fixtures for Familiar backend tests.

Uses FastAPI's synchronous TestClient which properly handles async endpoints
without the event loop complexities of using AsyncClient directly.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import (
    ArtistCheckCache,
    ExternalAlbumCache,
    Playlist,
    PlaylistTrack,
    ProfilePlayHistory,
    ProposedChange,
    SmartPlaylist,
    Track,
    TrackAnalysis,
)
from app.main import app


@pytest.fixture(autouse=True)
def deterministic_random():
    """Seed stdlib random for reproducible test runs."""
    import random
    random.seed(42)
    yield


@pytest.fixture(autouse=True)
def reset_artwork_fetcher():
    """Reset the artwork fetcher singleton between tests.

    This prevents asyncio loop issues when tests run with different event loops
    but share the global singleton.
    """
    import app.services.artwork_fetcher as af

    # Reset before test
    af._artwork_fetcher = None
    yield
    # Reset after test
    af._artwork_fetcher = None


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    """Provide a test client for the entire test session.

    Using session scope with proper context management.
    TestClient handles async endpoints synchronously, avoiding event loop issues.
    Must be session-scoped because the async engine's connection pool binds
    connections to a single event loop.
    """
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="function")
def test_profile(client: TestClient) -> dict:
    """Create a fresh test profile for each test function.

    Returns the profile data including 'id' for use in headers.
    """
    response = client.post(
        "/api/v1/profiles",
        json={"name": f"Test User {uuid4().hex[:8]}"},
    )
    assert response.status_code == 201, f"Failed to create profile: {response.text}"
    return response.json()


def make_profile_headers(profile: dict) -> dict[str, str]:
    """Create headers with profile ID for authenticated requests."""
    return {"X-Profile-ID": str(profile["id"])}


# ---------------------------------------------------------------------------
# Shared async DB fixture for integration tests
# ---------------------------------------------------------------------------

# Tables to clean in correct FK order (children before parents)
_CLEANUP_TABLES = [
    PlaylistTrack,
    Playlist,
    SmartPlaylist,
    ProposedChange,
    ProfilePlayHistory,
    ExternalAlbumCache,
    ArtistCheckCache,
    TrackAnalysis,
    Track,
]


@pytest_asyncio.fixture(scope="function")
async def async_db():
    """Provide a per-test async DB session against the real PostgreSQL database.

    Creates its own engine per test to avoid event-loop binding conflicts with
    the session-scoped TestClient. Cleans integration-test tables before and
    after each test.
    """
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        # Clean before test
        for model in _CLEANUP_TABLES:
            await session.execute(delete(model))
        await session.commit()

        yield session

        # Clean after test
        for model in _CLEANUP_TABLES:
            await session.execute(delete(model))
        await session.commit()

    await engine.dispose()


# ---------------------------------------------------------------------------
# Shared contract-test assertion helpers
# ---------------------------------------------------------------------------


def assert_error_shape(response, *, status_code: int) -> None:
    """Verify the standard error envelope: {error: true, status_code, message}."""
    assert response.status_code == status_code
    payload = response.json()
    assert isinstance(payload, dict)
    assert payload.get("error") is True
    assert isinstance(payload.get("message"), str)
    assert payload.get("status_code") == status_code


def assert_full_envelope(response, *, status_code: int) -> dict:
    """Strict envelope check — returns payload for further assertions."""
    assert_error_shape(response, status_code=status_code)
    payload = response.json()
    # message must be non-empty
    assert len(payload["message"]) > 0
    # detail and request_id are optional keys (only present when non-None)
    for key in ("detail", "request_id"):
        if key in payload:
            assert isinstance(payload[key], str)
    return payload
