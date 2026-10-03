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
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import (
    Artist,
    ArtistAlias,
    ArtistCheckCache,
    DiscoverySourceHealth,
    ExternalAlbumCache,
    ExternalArtistImageCache,
    MixTape,
    PlaybackSession,
    PlaybackSessionArchive,
    PlayEvent,
    Playlist,
    PlaylistTrack,
    ProfilePlayHistory,
    ProposedChange,
    SmartPlaylist,
    Track,
    TrackAnalysis,
    TrackVideo,
)
from app.main import app

# The app starts many times here, against fixture folders; a library watch (ADR-0142) on each would
# only add noise and background scans. Read at startup, so setting it here is enough.
settings.watch_library = False


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

# **Destructive, on purpose, and only because `conftest.py` at the rootdir has already proved the
# database is disposable** (ADR-0128 point 5). `async_db` deletes every row of these tables before
# and after each test — which, until that guard, it did to whatever `DATABASE_URL` named, the
# development library included. Deleting rather than wrapping each test in a transaction is
# deliberate: the application, its background work and the session-scoped client hold their own
# connections, and a rollback cannot take back what they wrote.
#
# Tables to clean in correct FK order (children before parents).
# ArtistAlias FKs to Artist with CASCADE; Track.canonical_artist_id FKs
# to Artist with SET NULL — so deleting tracks first then artists is safe.
_CLEANUP_TABLES = [
    # Seeded by its migration, so it survives between tests and one test's backoff
    # leaks into the next. Truncated here; the recorder recreates rows on demand.
    DiscoverySourceHealth,
    MixTape,
    PlaylistTrack,
    Playlist,
    SmartPlaylist,
    ProposedChange,
    PlayEvent,
    PlaybackSessionArchive,
    PlaybackSession,
    ProfilePlayHistory,
    ExternalAlbumCache,
    ArtistCheckCache,
    ExternalArtistImageCache,
    TrackAnalysis,
    # FKs to Track with CASCADE, so it goes before Track like TrackAnalysis does.
    TrackVideo,
    Track,
    ArtistAlias,
    Artist,
]


async def _reset_vector_state(engine) -> None:
    """Start every test from a vector index and planner statistics that describe what is there.

    The cleanup above is a DELETE, so every row a test removes stays in the HNSW index on
    `track_analysis.embedding` until something vacuums it. That was harmless until autovacuum
    analysed the tables mid-suite while a large fixture was loaded (the ambient pool's 150+ tracks):
    the planner then believed the tables held thousands of rows and sent every later similarity
    query through the index, whose bounded candidate list (`hnsw.ef_search`) could fill with dead
    rows, so three live rows came back as none. That is `assert 'Here' in []`,
    `test_agreement_outranks_proximity`'s IndexError and the excursion rate's "0 of 24", which
    failed together in suite order for weeks and never alone (docs/HEALTH.md). Reproduced on
    2026-10-03 by churning 2,100 analysed rows with an ANALYZE before the delete: the similarity
    tests then failed every run.

    VACUUM cannot run inside a transaction, hence its own autocommit connection.
    """
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("VACUUM ANALYZE tracks, track_analysis"))


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
        await _reset_vector_state(engine)

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
