"""Run the Familiar server as an ordinary process: `python -m app.serve` (ADR-0132 point 6).

This does what the container does between `docker/entrypoint.sh` and the Dockerfile's `CMD`: bring
the schema to head, then run uvicorn with one worker. It is the whole start-up for a server that is
not in Docker. Familiar Server (ADR-0136) runs it, and so can anyone with a Postgres that has
pgvector installed.

It does not install, find or start Postgres; that belongs to whatever packaged the server. It does
not stamp an old, pre-Alembic database as the entrypoint does either: that path exists for Docker
installs that predate migrations, and a server started this way has never had one.

The default host is loopback. Listening on anything else is a decision the caller makes with
`--host`; ADR-0134 decides what that requires.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from app.config import BACKEND_ROOT

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4400


def migrate() -> None:
    """Upgrade the database named by `DATABASE_URL` to head.

    The paths come from `BACKEND_ROOT` rather than the working directory, and the root goes on
    `sys.path` because `migrations/env.py` imports `migrations.helpers` as a top-level package.
    """
    from alembic import command
    from alembic.config import Config

    root = str(BACKEND_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")


def run(host: str, port: int) -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, workers=1)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.serve", description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"interface to bind (default {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT})")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    migrate: Callable[[], None] = migrate,
    run: Callable[[str, int], None] = run,
) -> None:
    args = parse_args(argv)
    migrate()
    run(args.host, args.port)


# Guarded: the analysis and scan pools use `spawn`, which re-imports the parent's main module in
# every child. Unguarded, each worker would start a server of its own.
if __name__ == "__main__":
    main()
