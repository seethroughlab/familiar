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

DUMP_FILE="$(mktemp -t demo-seed.XXXXXX.sql)"
trap 'rm -f "$DUMP_FILE"' EXIT

echo "→ Dumping profiles / tracks / track_analysis / artist_info (pg16 via container)…"
docker exec "$ANALYSIS_PG_CONTAINER" pg_dump \
    "postgresql://familiar:familiar@localhost:5432/familiar" \
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
echo "   $(basename "$DUMP_FILE") — ${BYTES} bytes"

echo "→ Ensuring pgvector extension on Neon…"
psql "$NEON_URL" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS vector;'

echo "→ Loading seed into Neon…"
psql "$NEON_URL" -v ON_ERROR_STOP=1 -f "$DUMP_FILE"

echo "→ Uploading audio files to Fly volume /data/music/ on ${FLY_APP}…"
# Build a single SFTP batch command to minimize ssh round-trips
SFTP_BATCH="$(mktemp -t fly-sftp.XXXXXX.txt)"
trap 'rm -f "$DUMP_FILE" "$SFTP_BATCH"' EXIT
{
    echo "-mkdir /data/music"
    for f in "$DEMO_LIBRARY_PATH"/*.mp3; do
        [ -f "$f" ] || continue
        echo "put \"$f\" /data/music/$(basename "$f")"
    done
} > "$SFTP_BATCH"

UPLOAD_COUNT=$(grep -c '^put ' "$SFTP_BATCH" || true)
echo "   uploading $UPLOAD_COUNT files…"
flyctl ssh sftp shell -a "${FLY_APP}" < "$SFTP_BATCH"

echo ""
echo "✓ Demo library seeded."
echo "  Verify with:"
echo "    curl -sS https://${FLY_APP}.fly.dev/api/v1/health"
echo "    curl -sS https://${FLY_APP}.fly.dev/api/v1/profiles"
