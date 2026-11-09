"""Print this server's sign-in link: `python -m app.token` (ADR-0141 point 2).

A new server prints the link once, at its first start. This prints it again, for an owner who lost
that log line: `docker exec familiar-api python -m app.token`.

`--create` makes a token when there is none, and is the recovery path ADR-0171 point 4 asks for: a
tokenless server answers only its own machine, so the owner may have no browser that can reach the
web admin to make one there. With a token already set, `--create` prints it rather than replacing
it: rotating signs every client out, so it is a deliberate `POST /api/v1/auth/token` with the
current token, never a side effect of recovering.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.token", description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "--create", action="store_true", help="make a token if this server has none, then print"
    )
    args = parser.parse_args(argv)

    from app.serve import configured_token, mint_token, sign_in_link

    token = configured_token()
    if not token and args.create:
        token = mint_token()
        print(
            "Made a token for this server. It takes effect at once: sign in with this link, "
            "then pair your devices under Server → Access.",
            file=sys.stderr,
        )
    if not token:
        print(
            "This server has no token, so it answers only its own machine, unless it was started "
            "open (FAMILIAR_OPEN_SERVER, or an existing library). Make one with "
            "`python -m app.token --create`, or under Server → Access in the web admin.",
            file=sys.stderr,
        )
        return 1
    print(sign_in_link(token))
    return 0


if __name__ == "__main__":
    sys.exit(main())
