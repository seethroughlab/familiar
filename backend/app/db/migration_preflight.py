"""Migration preflight checks for startup/CI.

Ensures database schema revision(s) match Alembic head(s).
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.config import settings


def check_database_at_head() -> tuple[bool, list[str], list[str], str | None]:
    """Return migration preflight status.

    Returns:
        (ok, current_revisions, head_revisions, reason_if_not_ok)
    """
    backend_dir = Path(__file__).resolve().parents[2]
    alembic_ini = backend_dir / "alembic.ini"
    migrations_dir = backend_dir / "migrations"

    if not alembic_ini.exists():
        return False, [], [], f"Missing alembic.ini at {alembic_ini}"
    if not migrations_dir.exists():
        return False, [], [], f"Missing migrations directory at {migrations_dir}"

    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(migrations_dir))
    script = ScriptDirectory.from_config(config)
    heads = sorted(script.get_heads())

    current_revisions: list[str] = []
    with create_engine(settings.sync_database_url, future=True).connect() as conn:
        has_version_table = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
        if has_version_table is None:
            return False, [], heads, "alembic_version table is missing"

        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        current_revisions = sorted(str(row[0]) for row in rows if row[0])

    if not current_revisions:
        return False, current_revisions, heads, "No applied alembic revisions found"

    if set(current_revisions) != set(heads):
        return (
            False,
            current_revisions,
            heads,
            "Current revision set does not match Alembic head set",
        )

    return True, current_revisions, heads, None


def assert_database_at_head() -> None:
    """Raise RuntimeError with actionable message when DB is not at head."""
    ok, current, heads, reason = check_database_at_head()
    if ok:
        return

    raise RuntimeError(
        "Database migration preflight failed. "
        f"reason={reason}; current={current}; heads={heads}. "
        "Run: alembic upgrade head"
    )
