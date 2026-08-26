#!/usr/bin/env bash
set -euo pipefail

# seed-demo-library.sh — Push a pre-analyzed local library into the Neon
# database + Fly volume that back the `familiar-demo` public review server.
#
# Run this *after* you have:
#   1. Populated ./demo-library/ with CC-licensed MP3s
#      (either manually or via scripts/fetch-demo-library.sh)
#   2. Run scripts/analyze-demo-library.sh — produces a throwaway local
#      Postgres with CLAP-embedded tracks + a "Demo" profile row
#   3. Provisioned Fly (deploy/fly/fly.toml) + Neon per the deployment plan
#
# Required env vars:
#   DEMO_LOCAL_DB     local postgres URL used to analyze the library
#                     (plain postgresql:// — no asyncpg+)
#   DEMO_NEON_URL     Neon connection string (plain postgresql://).
#                     IMPORTANT: use the *direct* host (no "-pooler" in the
#                     subdomain). Neon's pgbouncer pooler ignores role-level
#                     search_path, which breaks bare-table SQL in the backend.
#   FLY_APP           Fly app name, e.g. "familiar-demo"
#   DEMO_LIBRARY_PATH local folder of MP3s (default: ./demo-library)
#
# The server side reads file paths at /data/music/<basename>, so this script
# rewrites every tracks.file_path to that pattern before dumping.

: "${DEMO_LOCAL_DB:?set DEMO_LOCAL_DB to your local analysis postgres URL}"
: "${DEMO_NEON_URL:?set DEMO_NEON_URL to your Neon postgres URL}"
: "${FLY_APP:?set FLY_APP (e.g. familiar-demo)}"
DEMO_LIBRARY_PATH="${DEMO_LIBRARY_PATH:-./demo-library}"

command -v psql    >/dev/null || { echo "psql required" >&2; exit 1; }
command -v flyctl  >/dev/null || { echo "flyctl required" >&2; exit 1; }
command -v docker  >/dev/null || { echo "docker required" >&2; exit 1; }

# pg_dump needs to match the server version, which is pg16 on Neon + on the
# local analysis stack. Run it from inside the analysis Postgres container
# instead of trusting whatever pg_dump is on the user's PATH.
ANALYSIS_PG_CONTAINER="${ANALYSIS_PG_CONTAINER:-familiar-demo-analysis-postgres}"
docker inspect "$ANALYSIS_PG_CONTAINER" >/dev/null 2>&1 || {
    echo "Analysis Postgres container '$ANALYSIS_PG_CONTAINER' not running." >&2
    echo "Run scripts/analyze-demo-library.sh up first." >&2
    exit 1
}
[ -d "$DEMO_LIBRARY_PATH" ] || { echo "No such dir: $DEMO_LIBRARY_PATH" >&2; exit 1; }

# Strip asyncpg+ prefix if someone pasted the FastAPI-style URL
LOCAL_URL="${DEMO_LOCAL_DB/postgresql+asyncpg:/postgresql:}"
NEON_URL="${DEMO_NEON_URL/postgresql+asyncpg:/postgresql:}"

echo "→ Rewriting local tracks.file_path to /data/music/<basename>…"
psql "$LOCAL_URL" -v ON_ERROR_STOP=1 <<'SQL'
UPDATE tracks
SET file_path = '/data/music/' || regexp_replace(file_path, '^.*/', '');
SQL

# **The dump is kept, not thrown away.** It used to go to `mktemp` with a `trap` deleting it on
# exit, which meant the golden copy of the demo library was destroyed every time it was made — and
# the weekly reset job had nothing to restore from. It is now written into the repository, gzipped,
# and committed alongside the schema that produced it.
SEED_FILE="${SEED_FILE:-deploy/fly/demo-seed.sql.gz}"
DUMP_FILE="$(mktemp -t demo-seed.XXXXXX.sql)"
trap 'rm -f "$DUMP_FILE"' EXIT

echo "→ Dumping profiles / tracks / track_analysis / artist_info (pg16 via container)…"
docker exec "$ANALYSIS_PG_CONTAINER" pg_dump \
    "postgresql://familiar:familiar@localhost:5432/familiar" \
    --data-only \
    --no-owner \
    --no-privileges \
    --column-inserts \
    --strict-names \
    --table=profiles \
    --table=tracks \
    --table=track_analysis \
    > "$DUMP_FILE"

# **Normalise pg_dump 17's random restrict token.** It emits `\restrict <token>` / `\unrestrict
# <token>` with a fresh random token per dump — a psql-side guard against a dump injecting commands
# during restore. Random is right for a dump you were handed; here the file is committed and
# reviewed in a pull request, and a token that changes every run means two captures of *identical*
# data produce a diff, so "the library changed" becomes indistinguishable from "someone re-ran the
# script". The pair only has to match each other, so both are pinned to one value: the mechanism
# still works, and the artifact is deterministic.
sed -i.bak -E 's/^\\(restrict|unrestrict) .*/\\\1 familiar_demo_seed/' "$DUMP_FILE"
rm -f "$DUMP_FILE.bak"

BYTES=$(wc -c < "$DUMP_FILE" | tr -d ' ')
echo "   $(basename "$DUMP_FILE") — ${BYTES} bytes"

echo "→ Writing the golden seed to ${SEED_FILE}…"
mkdir -p "$(dirname "$SEED_FILE")"
# `-n` so identical data gzips to identical bytes — see capture-demo-seed.sh.
gzip -9 -n -c "$DUMP_FILE" > "$SEED_FILE"
GZ_BYTES=$(wc -c < "$SEED_FILE" | tr -d ' ')
echo "   ${SEED_FILE} — ${GZ_BYTES} bytes gzipped"
if [ "$GZ_BYTES" -gt 20000000 ]; then
    echo "   WARNING: over 20 MB. Committing this is questionable — consider a release asset" >&2
    echo "   and pointing the reset workflow at it instead." >&2
fi
echo "   Commit it: the weekly reset (.github/workflows/fly-reset-demo.yml) restores from this file."

echo "→ Ensuring pgvector extension on Neon…"
psql "$NEON_URL" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS vector;'

echo "→ Loading seed into Neon…"
psql "$NEON_URL" -v ON_ERROR_STOP=1 -f "$DUMP_FILE"

echo "→ Waking Fly machine (scaled to zero when idle)…"
# fly ssh sftp needs a running VM. A health-check poke boots it via
# auto_start_machines. 60s is generous for a cold start.
curl -fsS --max-time 60 "https://${FLY_APP}.fly.dev/api/v1/health" >/dev/null || {
    echo "   (warning: couldn't reach /health; continuing anyway)" >&2
}

echo "→ Uploading audio files to Fly volume /data/music/ on ${FLY_APP}…"
# Build a single SFTP batch command to minimize ssh round-trips.
# Note: paths are unquoted because Fly's sftp shell doesn't dequote — the
# fetch script keeps basenames slug-safe (letters/digits/dashes) so this
# is fine.
SFTP_BATCH="$(mktemp -t fly-sftp.XXXXXX.txt)"
trap 'rm -f "$DUMP_FILE" "$SFTP_BATCH"' EXIT
for f in "$DEMO_LIBRARY_PATH"/*.mp3; do
    [ -f "$f" ] || continue
    echo "put $f /data/music/$(basename "$f")"
done > "$SFTP_BATCH"

UPLOAD_COUNT=$(grep -c '^put ' "$SFTP_BATCH" || true)
echo "   uploading $UPLOAD_COUNT files…"
# Ensure /data/music exists (sftp's -mkdir is not supported by Fly's shell).
flyctl ssh console -a "${FLY_APP}" -C 'bash -c "mkdir -p /data/music"' >/dev/null 2>&1 || true
flyctl ssh sftp shell -a "${FLY_APP}" < "$SFTP_BATCH"

echo ""
echo "✓ Demo library seeded."
echo "  Verify with:"
echo "    curl -sS https://${FLY_APP}.fly.dev/api/v1/health"
echo "    curl -sS https://${FLY_APP}.fly.dev/api/v1/profiles"
