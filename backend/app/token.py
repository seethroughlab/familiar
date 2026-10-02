"""Print this server's sign-in link: `python -m app.token` (ADR-0141 point 2).

A new server prints the link once, at its first start. This prints it again, for an owner who lost
that log line: `docker exec familiar-api python -m app.token`.
"""

from __future__ import annotations

import sys


def main() -> int:
    from app.serve import configured_token, sign_in_link

    token = configured_token()
    if not token:
        print(
            "This server has no token: anyone who can reach it can use it. Create one under "
            "Server → Access in the web admin.",
            file=sys.stderr,
        )
        return 1
    print(sign_in_link(token))
    return 0


if __name__ == "__main__":
    sys.exit(main())
