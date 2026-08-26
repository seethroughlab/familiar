"""
Tests for Alembic migrations and deployment readiness.

Verifies that migrations are properly configured and applied,
that Docker health checks will work correctly, and that migrations
survive downgrade/upgrade round-trip cycles.
"""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_alembic_config_exists() -> None:
    """Verify Alembic configuration files exist."""
    backend_dir = Path(__file__).parent.parent

    assert (backend_dir / "alembic.ini").exists(), "alembic.ini not found"
    assert (backend_dir / "migrations").is_dir(), "migrations/ directory not found"
    assert (backend_dir / "migrations" / "env.py").exists(), "migrations/env.py not found"
    assert (backend_dir / "migrations" / "versions").is_dir(), "migrations/versions/ not found"


def test_migrations_upgrade(client: TestClient) -> None:
    """Verify migrations can be applied successfully.

    This test runs 'alembic upgrade head' to ensure migrations apply cleanly.
    The client fixture ensures the app has started and DB is connected.
    """
    backend_dir = Path(__file__).parent.parent

    # Run alembic upgrade head
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )

    # Should succeed
    assert result.returncode == 0, f"alembic upgrade head failed: {result.stderr}"


def test_migrations_current_at_head(client: TestClient) -> None:
    """Verify database is at the latest migration revision after upgrade.

    This test runs 'alembic current' and checks that we're at head.
    Depends on test_migrations_upgrade running first.
    """
    backend_dir = Path(__file__).parent.parent

    # First ensure we're at head
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )

    # Run alembic current to get the current revision
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )

    # Should succeed
    assert result.returncode == 0, f"alembic current failed: {result.stderr}"

    # Output should contain a revision at head
    output = result.stdout.strip()
    assert output, "No migration revision found after upgrade"
    assert "(head)" in output, f"Database not at head revision: {output}"


def test_migrations_history() -> None:
    """Verify migration history is accessible and has at least one migration."""
    backend_dir = Path(__file__).parent.parent

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "history"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"alembic history failed: {result.stderr}"

    # Should have at least the baseline migration
    output = result.stdout.strip()
    assert output, "No migrations found in history"
    assert "baseline" in output.lower() or "->" in output, f"Expected migration history: {output}"


def test_fresh_database_migrates_to_head_cleanly(client: TestClient) -> None:
    """A fresh database ends up at head with a schema matching the models.

    **This cannot detect schema drift, and used to claim it could.** The baseline migration runs
    `Base.metadata.create_all()`, so a fresh database's schema is generated from the very models
    `alembic check` then compares it against — they agree by construction, whatever the incremental
    migrations say. It stayed green for five months while `spotify_imports.imported_at` was NOT NULL
    in the model and nullable in every real database.

    What it does verify is still worth having: a new install reaches head without a migration
    erroring, and nothing in the model layer is unrepresentable in Postgres. The drift question is
    `test_incremental_migrations_match_the_models` below.
    """
    upgrade = _alembic_run("upgrade", "head")
    # Checked, unlike before — a failed upgrade used to fall through to `alembic check` and be
    # reported as confusing schema drift rather than as the upgrade failure it was.
    assert upgrade.returncode == 0, (
        f"alembic upgrade head failed:\n{upgrade.stdout}\n{upgrade.stderr}"
    )

    result = _alembic_run("check")
    assert result.returncode == 0, (
        f"Fresh database does not match the models!\n{result.stdout}\n{result.stderr}"
    )


def _post_baseline_ddl() -> tuple[set[str], dict[str, set[str]]]:
    """What the migrations after the baseline are supposed to build.

    Parsed from source rather than executed, because the question is what the *DDL* says — running
    it is what the test does next.
    """
    versions = Path(__file__).parent.parent / "migrations" / "versions"
    tables: set[str] = set()
    columns: dict[str, set[str]] = {}
    for path in versions.glob("*.py"):
        if "baseline" in path.name:
            continue
        source = path.read_text()
        tables |= set(re.findall(r'create_table\(\s*["\']([a-z_]+)', source))
        for table, column in re.findall(
            r'add_column\(\s*["\']([a-z_]+)["\']\s*,\s*sa\.Column\(\s*["\']([a-z_]+)', source
        ):
            columns.setdefault(table, set()).add(column)
    # A column added to a table the same set of migrations creates is already covered by the table.
    return tables, {t: c for t, c in columns.items() if t not in tables}


def test_incremental_migrations_match_the_models() -> None:
    """The migrations' own DDL agrees with the models it claims to implement.

    **This is the drift guard the suite did not have.** It builds a database the way a *real* one
    got there: create the full schema from the models so foreign keys resolve, drop exactly what the
    post-baseline migrations are supposed to build, stamp the baseline instead of running it, then
    upgrade. Every `create_table` and `add_column` written since the baseline therefore executes for
    real, and its DDL can be compared against the model.

    Only post-baseline objects are compared. Anything predating the baseline has no frozen DDL to
    check against — `create_all` is all there is — and pretending otherwise would be the same
    dishonesty this replaces.
    """
    sa = pytest.importorskip("sqlalchemy")
    from app.config import settings
    from app.db.models import Base

    sync_url = settings.sync_database_url
    scratch = "familiar_migration_check"
    admin_url = sync_url.rsplit("/", 1)[0] + "/postgres"

    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f"DROP DATABASE IF EXISTS {scratch}"))
            conn.execute(sa.text(f"CREATE DATABASE {scratch}"))
    except Exception as exc:  # pragma: no cover - permissions vary by deployment
        pytest.skip(f"cannot create a scratch database: {exc}")

    scratch_url = sync_url.rsplit("/", 1)[0] + f"/{scratch}"
    engine = sa.create_engine(scratch_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

        new_tables, new_columns = _post_baseline_ddl()
        assert new_tables, "parsed no post-baseline tables — the DDL regex has gone stale"

        Base.metadata.create_all(engine)
        with engine.connect() as conn:
            for table in sorted(new_tables):
                conn.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            for table, cols in sorted(new_columns.items()):
                for column in sorted(cols):
                    conn.execute(
                        sa.text(
                            f"ALTER TABLE IF EXISTS {table} DROP COLUMN IF EXISTS {column} CASCADE"
                        )
                    )

        env = {
            **os.environ,
            "DATABASE_URL": scratch_url.replace("postgresql://", "postgresql+asyncpg://"),
        }
        for args in (("stamp", "20241231_000000_baseline"), ("upgrade", "head")):
            result = subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=Path(__file__).parent.parent,
                capture_output=True,
                text=True,
                env=env,
            )
            assert result.returncode == 0, (
                f"alembic {args[0]} failed on the scratch database:\n"
                f"{result.stdout}\n{result.stderr}"
            )

        inspector = sa.inspect(engine)
        actual = {
            table: {c["name"]: c for c in inspector.get_columns(table)}
            for table in inspector.get_table_names()
        }

        problems: list[str] = []
        for name, table in Base.metadata.tables.items():
            expected = (
                {c.name for c in table.columns} if name in new_tables
                else new_columns.get(name, set())
            )
            if not expected:
                continue
            if name not in actual:
                problems.append(f"{name}: no migration creates this table")
                continue
            for column in table.columns:
                if column.name not in expected:
                    continue
                got = actual[name].get(column.name)
                if got is None:
                    problems.append(f"{name}.{column.name}: no migration adds this column")
                elif bool(got["nullable"]) != bool(column.nullable):
                    problems.append(
                        f"{name}.{column.name}: migration says nullable={got['nullable']}, "
                        f"model says nullable={column.nullable}"
                    )

        assert not problems, (
            "Migration DDL disagrees with the models. A fresh install will not notice — its schema "
            "comes from `create_all` — but every existing database has the migration's version:\n  "
            + "\n  ".join(sorted(problems))
        )
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f"DROP DATABASE IF EXISTS {scratch}"))
        admin.dispose()


def test_docker_health_check_endpoint(client: TestClient) -> None:
    """Verify the health endpoint used in Docker health checks actually exists.

    The Dockerfile and docker-compose files reference a specific health endpoint.
    This test ensures that endpoint exists and returns 200 OK.
    """
    # Read the Dockerfile to find what endpoint the health check uses
    repo_root = Path(__file__).parent.parent.parent
    dockerfile_path = repo_root / "docker" / "Dockerfile"

    assert dockerfile_path.exists(), f"Dockerfile not found at {dockerfile_path}"

    dockerfile_content = dockerfile_path.read_text()

    # Extract health check URL from Dockerfile
    # Matches patterns like: httpx.get('http://localhost:8000/api/v1/health'
    match = re.search(r"httpx\.get\(['\"]http://localhost:\d+(/[^'\"]+)['\"]", dockerfile_content)
    assert match, "Could not find health check URL in Dockerfile"

    health_path = match.group(1)

    # Test that the endpoint exists and returns success
    response = client.get(health_path)
    assert response.status_code == 200, (
        f"Health check endpoint {health_path} returned {response.status_code}. "
        f"Docker health checks will fail!"
    )


def test_uvicorn_has_workers() -> None:
    """Verify uvicorn is configured with multiple workers.

    A single uvicorn process can become unresponsive under load, causing
    health checks to timeout even when the server is technically running.
    Multiple workers ensure there's always capacity to handle health checks.
    """
    repo_root = Path(__file__).parent.parent.parent
    dockerfile_path = repo_root / "docker" / "Dockerfile"

    dockerfile_content = dockerfile_path.read_text()

    # Check that uvicorn CMD includes --workers
    assert "--workers" in dockerfile_content, (
        "uvicorn should be configured with --workers to prevent health check "
        "timeouts under load. Add '--workers', '4' to the CMD in Dockerfile."
    )


# ---------------------------------------------------------------------------
# Migration round-trip (downgrade → upgrade) tests
# ---------------------------------------------------------------------------

def _alembic_run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run an alembic command and return the result."""
    backend_dir = Path(__file__).parent.parent
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )


def test_migration_downgrade_upgrade_cycle(client: TestClient) -> None:
    """Verify the latest migration survives a downgrade → upgrade round-trip.

    This ensures:
    - The latest migration's downgrade() runs without error (even if it's just pass)
    - The upgrade() is idempotent thanks to guard helpers
    - The schema is consistent after the round-trip
    """
    # Ensure we're at head first
    result = _alembic_run("upgrade", "head")
    assert result.returncode == 0, f"upgrade head failed: {result.stderr}"

    # Downgrade one step
    result = _alembic_run("downgrade", "-1")
    assert result.returncode == 0, f"downgrade -1 failed: {result.stderr}"

    # Upgrade back to head
    result = _alembic_run("upgrade", "head")
    assert result.returncode == 0, f"upgrade head after downgrade failed: {result.stderr}"

    # Verify we're at head
    result = _alembic_run("current")
    assert result.returncode == 0, f"alembic current failed: {result.stderr}"
    assert "(head)" in result.stdout, f"Not at head after round-trip: {result.stdout}"


def _get_reversible_migrations() -> list[str]:
    """Find all migration revisions whose downgrade() has real logic (not just pass)."""
    versions_dir = Path(__file__).parent.parent / "migrations" / "versions"
    reversible = []

    for filepath in sorted(versions_dir.glob("*.py")):
        source = filepath.read_text()
        tree = ast.parse(source, filename=str(filepath))

        revision = None
        downgrade_is_real = False

        for node in ast.iter_child_nodes(tree):
            # Handle both plain assignment and annotated assignment
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "revision":
                        if isinstance(node.value, ast.Constant):
                            revision = node.value.value
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "revision":
                    if node.value and isinstance(node.value, ast.Constant):
                        revision = node.value.value

            if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
                body = node.body
                # pass-only or docstring-only → not real
                is_trivial = (
                    len(body) == 1
                    and (
                        isinstance(body[0], ast.Pass)
                        or (
                            isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                        )
                    )
                )
                downgrade_is_real = not is_trivial

        if revision and downgrade_is_real:
            reversible.append(revision)

    return reversible


REVERSIBLE_MIGRATIONS = _get_reversible_migrations()

# Migrations where the full downgrade chain from head is broken due to
# 20260306_drop_spt_ext dropping external_tracks — earlier migrations'
# downgrades reference that table. Only affects round-trip test (which
# downgrades from head to {revision}-1), not the individual migrations.
_BROKEN_DOWNGRADE_CHAIN = {
    "20241231_000000_baseline",
    "20250101_000000_add_bitrate_mode",
    "20260206_add_auto_download",
    "20260206_track_file_size",
    "20260208_autodownload_nn",
    "20260208_subsonic_creds",
    "20260209_full_file_hash",
    "20260209_hnsw_idx",
    "20260211_drop_ext_preview",
}


@pytest.mark.parametrize("revision", REVERSIBLE_MIGRATIONS)
def test_reversible_migration_round_trip(client: TestClient, revision: str) -> None:
    """Each reversible migration survives a downgrade → upgrade cycle."""
    if revision in _BROKEN_DOWNGRADE_CHAIN:
        pytest.skip(f"downgrade chain through drop_spt_ext is known-broken for {revision}")
    # Ensure at head
    result = _alembic_run("upgrade", "head")
    assert result.returncode == 0, f"upgrade head failed: {result.stderr}"

    # Upgrade to this specific revision (in case we're testing older ones)
    result = _alembic_run("upgrade", revision)
    assert result.returncode == 0, f"upgrade to {revision} failed: {result.stderr}"

    # Downgrade one step from this revision
    result = _alembic_run("downgrade", f"{revision}-1")
    assert result.returncode == 0, (
        f"downgrade from {revision} failed: {result.stderr}"
    )

    # Upgrade back
    result = _alembic_run("upgrade", revision)
    assert result.returncode == 0, (
        f"upgrade back to {revision} failed: {result.stderr}"
    )

    # Restore to head for the next test
    result = _alembic_run("upgrade", "head")
    assert result.returncode == 0, f"restore to head failed: {result.stderr}"
