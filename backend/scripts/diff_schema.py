"""Diff a live database's schema against what the models would create.

**Why this exists.** `20241231_000000_baseline.py` builds fresh databases with
`Base.metadata.create_all()`, so their tables and columns come from the models and the later
migrations mostly no-op. That invites the question of whether the migration history could be
collapsed into a new baseline — and the answer depends on what the models *cannot* express.

Run against the NAS, this reports eight indexes that exist in every migrated database and in no
model: the HNSW index pgvector similarity search depends on, three trigram GIN indexes behind
search, three functional `lower(trim(...))` indexes, and a partial index on pending review. They are
created by migrations and `create_all` knows nothing about them, so a squash to a `create_all`
baseline would drop all eight — silently, and on fresh installs too.

Anything this reports is a difference that a squash would make permanent and undetectable. Get it to
zero first — by declaring the missing objects on the models — and a squash becomes safe.

Usage::

    # Compare the NAS against the models (reads over ssh; runs no DDL there)
    uv run python scripts/diff_schema.py --ssh jeff@openmediavault --container familiar-postgres

    # Compare any reachable database
    uv run python scripts/diff_schema.py --url postgresql://user:pass@host:5432/familiar

The live side is **read-only** — every query is a SELECT against catalogue views. The models side is
built in a scratch database created and dropped locally.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlalchemy as sa  # noqa: E402

SCRATCH = "familiar_schema_diff"

COLUMNS_SQL = """
select coalesce(json_agg(row_to_json(t)), '[]'::json) from (
  select table_name, column_name, data_type, udt_name, is_nullable,
         column_default, character_maximum_length, numeric_precision, numeric_scale
  from information_schema.columns
  where table_schema = 'public'
  order by table_name, column_name
) t
"""

INDEXES_SQL = """
select coalesce(json_agg(row_to_json(t)), '[]'::json) from (
  select tablename as table_name, indexdef
  from pg_indexes where schemaname = 'public'
  order by tablename, indexdef
) t
"""

CONSTRAINTS_SQL = """
select coalesce(json_agg(row_to_json(t)), '[]'::json) from (
  select conrelid::regclass::text as table_name,
         pg_get_constraintdef(oid) as def
  from pg_constraint
  where connamespace = 'public'::regnamespace
  order by 1, 2
) t
"""


def _via_ssh(host: str, container: str, database: str, user: str, sql: str) -> Any:
    """Run a read-only query inside the remote container and return the parsed JSON.

    The SQL travels on stdin rather than in the command string: it contains quotes and casts that
    do not survive two levels of shell quoting (ssh, then docker exec).
    """
    remote = f"docker exec -i {container} psql -U {user} -d {database} -tA -f -"
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", host, remote],
        input=sql, capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise SystemExit(f"ssh query failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout.strip() or "[]")


def _via_url(engine: sa.Engine, sql: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(sa.text(sql)).scalar() or []


def _build_models_schema(admin_url: str) -> tuple[sa.Engine, str]:
    """Create a scratch database holding exactly what the models describe."""
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        conn.execute(sa.text(f"CREATE DATABASE {SCRATCH}"))
    admin.dispose()

    scratch_url = admin_url.rsplit("/", 1)[0] + f"/{SCRATCH}"
    engine = sa.create_engine(scratch_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    from app.db.models import Base

    Base.metadata.create_all(engine)
    return engine, scratch_url


def _key_columns(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["table_name"], r["column_name"]): r for r in rows}


def _normalise_default(value: str | None) -> str | None:
    """Strip the noise that makes identical defaults look different."""
    if value is None:
        return None
    v = value.strip()
    # `'[]'::jsonb` vs `'[]'::jsonb`, `now()` vs `CURRENT_TIMESTAMP`, casts on enums, etc.
    v = v.replace("CURRENT_TIMESTAMP", "now()")
    v = v.replace("::character varying", "").replace("::text", "")
    return v


COMPARED = ("data_type", "udt_name", "is_nullable")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ssh", help="ssh target running the live database in Docker")
    ap.add_argument("--container", default="familiar-postgres")
    ap.add_argument("--url", help="direct connection URL to the live database")
    ap.add_argument("--database", default="familiar")
    ap.add_argument("--user", default="familiar")
    ap.add_argument("--show-defaults", action="store_true",
                    help="also report column default differences (noisy; often cosmetic)")
    args = ap.parse_args()

    if not args.ssh and not args.url:
        ap.error("pass --ssh or --url")

    from app.config import settings

    admin_url = settings.sync_database_url.rsplit("/", 1)[0] + "/postgres"

    if args.url:
        live_engine = sa.create_engine(args.url)
        live = {name: _via_url(live_engine, sql) for name, sql in
                (("columns", COLUMNS_SQL), ("indexes", INDEXES_SQL), ("constraints", CONSTRAINTS_SQL))}
        live_engine.dispose()
        source = args.url.rsplit("@", 1)[-1]
    else:
        live = {name: _via_ssh(args.ssh, args.container, args.database, args.user, sql)
                for name, sql in
                (("columns", COLUMNS_SQL), ("indexes", INDEXES_SQL), ("constraints", CONSTRAINTS_SQL))}
        source = f"{args.ssh}:{args.container}"

    engine, _ = _build_models_schema(admin_url)
    try:
        models = {name: _via_url(engine, sql) for name, sql in
                  (("columns", COLUMNS_SQL), ("indexes", INDEXES_SQL), ("constraints", CONSTRAINTS_SQL))}
    finally:
        engine.dispose()
        admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(sa.text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        admin.dispose()

    live_cols, model_cols = _key_columns(live["columns"]), _key_columns(models["columns"])
    live_tables = {t for t, _ in live_cols}
    model_tables = {t for t, _ in model_cols}

    print(f"live:   {source}  ({len(live_tables)} tables, {len(live_cols)} columns)")
    print(f"models: create_all  ({len(model_tables)} tables, {len(model_cols)} columns)")
    print()

    findings: dict[str, list[str]] = {
        "Tables only in the live database": [],
        "Tables the models define but the live database lacks": [],
        "Columns only in the live database": [],
        "Columns the models define but the live database lacks": [],
        "Columns whose definition differs": [],
    }

    # `alembic_version` is alembic's own bookkeeping and is never in the models.
    for t in sorted(live_tables - model_tables - {"alembic_version"}):
        findings["Tables only in the live database"].append(t)
    for t in sorted(model_tables - live_tables):
        findings["Tables the models define but the live database lacks"].append(t)

    shared_tables = live_tables & model_tables
    for key in sorted(live_cols.keys() - model_cols.keys()):
        if key[0] in shared_tables:
            findings["Columns only in the live database"].append(f"{key[0]}.{key[1]}")
    for key in sorted(model_cols.keys() - live_cols.keys()):
        if key[0] in shared_tables:
            findings["Columns the models define but the live database lacks"].append(f"{key[0]}.{key[1]}")

    for key in sorted(live_cols.keys() & model_cols.keys()):
        a, b = live_cols[key], model_cols[key]
        diffs = [f"{f}: live={a[f]!r} models={b[f]!r}" for f in COMPARED if a[f] != b[f]]
        if args.show_defaults:
            da, db = _normalise_default(a["column_default"]), _normalise_default(b["column_default"])
            if da != db:
                diffs.append(f"default: live={da!r} models={db!r}")
        if diffs:
            findings["Columns whose definition differs"].append(
                f"{key[0]}.{key[1]} — " + "; ".join(diffs)
            )

    # Indexes and constraints compared by definition rather than name: alembic and `create_all`
    # generate different auto-names for the same object, and a name difference is not a schema
    # difference.
    def _defs(rows: list[dict], field: str) -> set[str]:
        out = set()
        for r in rows:
            if r["table_name"] in shared_tables:
                out.add(" ".join(r[field].split()).replace("USING btree ", ""))
        return out

    live_idx, model_idx = _defs(live["indexes"], "indexdef"), _defs(models["indexes"], "indexdef")
    live_con, model_con = _defs(live["constraints"], "def"), _defs(models["constraints"], "def")

    findings["Indexes only in the live database"] = sorted(live_idx - model_idx)
    findings["Indexes the models define but the live database lacks"] = sorted(model_idx - live_idx)
    findings["Constraints only in the live database"] = sorted(live_con - model_con)
    findings["Constraints the models define but the live database lacks"] = sorted(model_con - live_con)

    total = sum(len(v) for v in findings.values())
    for heading, items in findings.items():
        if not items:
            continue
        print(f"### {heading} ({len(items)})")
        for item in items:
            print(f"  {item}")
        print()

    if total == 0:
        print("No differences. The live database already matches what the models would create,")
        print("so collapsing the migrations into a `create_all` baseline would freeze it as-is.")
    else:
        print(f"{total} difference(s).")
        print("Each one is something a squash would make permanent and undetectable — the migration")
        print("history is currently the only record that the live schema was built any other way.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
