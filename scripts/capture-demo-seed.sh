#!/usr/bin/env bash
set -euo pipefail

# capture-demo-seed.sh — Write the demo's current database out to the golden seed file.
#
#   DEMO_NEON_URL=postgresql://... ./scripts/capture-demo-seed.sh
#
# **Why this exists separately from `seed-demo-library.sh`.** That script builds the demo library
# from nothing: fetch the MP3s, stand up a throwaway Postgres, run a full analysis pass, then push
# the result to Neon. It is the right tool when the library changes, and it takes hours.
#
# This is for the ordinary case — the demo database is already correct and you want a restorable
# copy of it. That is most of the time, and especially right after a fresh seed, before anyone has
# played anything.
#
# The output is what `.github/workflows/fly-reset-demo.yml` restores every week. Commit it.
#
# **Capture from a clean demo.** This snapshots whatever is there, so running it after strangers
# have been playing bakes their play counts, favourites and skip history into the golden copy —
# which is precisely what the reset exists to remove. The script prints the play-event count and
# refuses above a threshold rather than letting that happen silently.

SEED_FILE="${SEED_FILE:-deploy/fly/demo-seed.sql.gz}"
: "${DEMO_NEON_URL:?set DEMO_NEON_URL to the demo Neon URL - use the direct host, not -pooler}"

# Neon's pgbouncer ignores `ALTER ROLE SET search_path`, so bare-table SQL through the pooler does
# not find the schema. Same rule as the seed script and the reset workflow.
case "$DEMO_NEON_URL" in
    *-pooler.*)
        echo "DEMO_NEON_URL points at Neon's pooler. Use the direct host." >&2
        exit 1
        ;;
esac

NEON_URL="${DEMO_NEON_URL/postgresql+asyncpg:/postgresql:}"

command -v docker >/dev/null || { echo "docker required (for a pg16-matched pg_dump)" >&2; exit 1; }

# pg_dump must match the server major version, which is 16 on Neon. Running it from the official
# image rather than trusting whatever is on PATH — a pg15 client against a pg16 server fails with a
# version error that reads like a connection problem.
PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"

echo "→ Checking what is in there…"
# **A failed query must not read as an empty database.** The first version of this ended in
# `2>/dev/null || echo "0"`, so an unreachable host, a bad password or a typo in the URL all came
# back as "0 play events" — a clean bill of health for a database it had never spoken to. It then
# went on to dump, and the dump failed with the real error a step later. The guard has to be able to
# tell "nothing has happened here" from "I could not ask".
set +e
PLAY_EVENTS=$(docker run --rm "$PG_IMAGE" \
    psql "$NEON_URL" -t -A -c "SELECT count(*) FROM play_events" 2>&1)
PSQL_STATUS=$?
set -e

if [ "$PSQL_STATUS" -ne 0 ] || ! printf '%s' "$PLAY_EVENTS" | grep -qE '^[0-9]+$'; then
    echo >&2
    echo "Could not read the demo database, so there is nothing to capture." >&2
    echo "psql said:" >&2
    printf '  %s\n' "$PLAY_EVENTS" >&2
    echo >&2
    echo "Check DEMO_NEON_URL — it must be a real Neon URL on the direct host." >&2
    exit 1
fi
echo "   play_events: ${PLAY_EVENTS}"

MAX_EVENTS="${MAX_EVENTS:-25}"
if [ "$PLAY_EVENTS" -gt "$MAX_EVENTS" ] && [ "${ALLOW_DIRTY:-}" != "1" ]; then
    echo >&2
    echo "Refusing: ${PLAY_EVENTS} play events is more than ${MAX_EVENTS}, so this database has" >&2
    echo "been used. Capturing it would bake that into the copy the weekly reset restores." >&2
    echo >&2
    echo "Either reset the demo first, or set ALLOW_DIRTY=1 if you know this is what you want." >&2
    exit 1
fi

DUMP_FILE="$(mktemp -t demo-seed.XXXXXX.sql)"
trap 'rm -f "$DUMP_FILE"' EXIT

# The same four tables `seed-demo-library.sh` dumps, in the same shape, so the two produce
# interchangeable files. `--column-inserts` keeps it diffable and restore-order independent.
echo "→ Dumping profiles / artist_info / tracks / track_analysis…"
docker run --rm "$PG_IMAGE" \
    pg_dump "$NEON_URL" \
    --data-only \
    --no-owner \
    --no-privileges \
    --column-inserts \
    --table=profiles \
    --table=artist_info \
    --table=tracks \
    --table=track_analysis \
    > "$DUMP_FILE"

BYTES=$(wc -c < "$DUMP_FILE" | tr -d ' ')
[ "$BYTES" -gt 1000 ] || { echo "Dump is only ${BYTES} bytes — that is not a library." >&2; exit 1; }

mkdir -p "$(dirname "$SEED_FILE")"
gzip -9 -c "$DUMP_FILE" > "$SEED_FILE"

GZ_BYTES=$(wc -c < "$SEED_FILE" | tr -d ' ')
echo "→ ${SEED_FILE} — ${BYTES} bytes raw, ${GZ_BYTES} bytes gzipped"
echo
echo "Commit it. The weekly reset restores from this file."
