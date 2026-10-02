"""Run the Familiar server as an ordinary process: `python -m app.serve` (ADR-0132 point 6).

This does what the container does between `docker/entrypoint.sh` and the Dockerfile's `CMD`: bring
the schema to head, then run uvicorn with one worker. It is the whole start-up for a server that is
not in Docker. Familiar Server (ADR-0136) runs it, and so can anyone with a Postgres that has
pgvector installed.

It does not install, find or start Postgres; that belongs to whatever packaged the server. It does
not stamp an old, pre-Alembic database as the entrypoint does either: that path exists for Docker
installs that predate migrations, and a server started this way has never had one.

The default host is loopback. Listening on anything else is where tokens are decided (ADR-0141),
after the migration, because "new server" means an empty library:

- a server with a token serves, and advertises `_familiar._tcp` on its port so a phone can find it
  (unless `--no-advertise`: the Docker image, whose container port is not the one anyone reaches);
- a **new** server, with no token and no tracks, mints one and prints a sign-in link to its log;
- an **existing** server with no token keeps serving, as it always has, and says at every start
  that anyone who can reach it can use it;
- `FAMILIAR_OPEN_SERVER=1` runs without a token on purpose (the public demo), and says so once.

This replaced ADR-0045 point 5's refusal, which as written would have taken every existing tokenless
server offline on the upgrade that shipped it. Familiar Server starts on loopback and mints its own
token through the API (ADR-0134 point 2), so none of this applies to it until it already has one.
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from collections.abc import Callable, Sequence
from enum import Enum

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
    parser.add_argument(
        "--no-advertise", dest="advertise", action="store_false",
        help="do not announce _familiar._tcp (the Docker image: its container port is not the host's)",
    )
    return parser.parse_args(argv)


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a host name other than localhost: assume it is reachable


def configured_token() -> str | None:
    from app.services.app_settings import get_app_settings_service

    return get_app_settings_service().get().access_token


class Start(Enum):
    """What a server listening beyond loopback does about its token (ADR-0141)."""

    HAS_TOKEN = "has a token"
    OPEN_BY_CHOICE = "open by choice"
    NEW = "new: mint a token"
    EXISTING_OPEN = "existing, open"


def decide(*, token: str | None, open_server: bool, has_tracks: Callable[[], bool]) -> Start:
    """The decision alone, without doing any of it. `has_tracks` is only asked when it matters."""
    if token:
        return Start.HAS_TOKEN
    if open_server:
        return Start.OPEN_BY_CHOICE
    return Start.EXISTING_OPEN if has_tracks() else Start.NEW


def library_has_tracks() -> bool:
    """Whether this server has imported anything: the same "new" a first import uses."""
    import asyncio

    from sqlalchemy import exists, select
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings
    from app.db.models import Track

    async def query() -> bool:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as connection:
                return bool(await connection.scalar(select(exists().select_from(Track.__table__))))
        finally:
            await engine.dispose()

    return asyncio.run(query())


def mint_token() -> str:
    """The token "Create server token" makes, stored where it does."""
    from app.api.auth import generate_token
    from app.services.app_settings import get_app_settings_service

    token = generate_token()
    get_app_settings_service().update(access_token=token)
    return token


def sign_in_link(token: str) -> str:
    """A link that signs the web admin in (`takeTokenFromFragment`). From `FRONTEND_URL` when set;
    otherwise the owner fills in the address, because a container cannot know the name it is
    reached by, nor the port it was published on."""
    from app.config import settings

    base = (settings.frontend_url or "http://<this server's address>:<port, 4400 by default>").rstrip("/")
    return f"{base}/#token={token}"


def say(message: str) -> None:
    """Before uvicorn configures logging: straight to the log the owner reads (`docker logs`)."""
    print(f"familiar: {message}", file=sys.stderr, flush=True)


def main(
    argv: Sequence[str] | None = None,
    *,
    migrate: Callable[[], None] = migrate,
    run: Callable[[str, int], None] = run,
    token: Callable[[], str | None] = configured_token,
    has_tracks: Callable[[], bool] = library_has_tracks,
    mint: Callable[[], str] = mint_token,
) -> Start | None:
    args = parse_args(argv)
    migrate()
    start = None
    if not is_loopback(args.host):
        from app.config import settings

        start = decide(token=token(), open_server=settings.open_server, has_tracks=has_tracks)
        if start is Start.NEW:
            say("this is a new server, so it has made itself a token (ADR-0141). Sign in to the web "
                f"admin with this link, then pair your devices there:\n\n    {sign_in_link(mint())}\n\n"
                "Run `python -m app.token` to see it again.")
        elif start is Start.EXISTING_OPEN:
            say("WARNING: this server has no token, so anyone who can reach it can use it. Create one "
                "under Server → Access in the web admin; every client then pairs once.")
        elif start is Start.OPEN_BY_CHOICE:
            say("running without a token by choice (FAMILIAR_OPEN_SERVER).")
        if start in (Start.HAS_TOKEN, Start.NEW) and args.advertise and settings.advertise_port is None:
            settings.advertise_port = args.port
    run(args.host, args.port)
    return start


# Guarded: the analysis and scan pools use `spawn`, which re-imports the parent's main module in
# every child. Unguarded, each worker would start a server of its own.
if __name__ == "__main__":
    main()
