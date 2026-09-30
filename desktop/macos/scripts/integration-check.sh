#!/bin/bash
# End-to-end check of the assembled app (ADR-0136): the real bundle, in the real sandbox.
#
#   1. a folder with one real 40-second FLAC, granted read-only
#   2. the Postgres agent started by hand (launchd would, after a Login Items approval)
#   3. the app launched in its debug integration mode (no folder picker, agent already running)
#   4. the server comes up, mints its own token, scans the track and analyses it: the analysis
#      pool running inside the sandbox is ADR-0136 point 3's whole question
#   5. the music folder is exactly as it was
#   6. everything stopped and removed: the app's container, the group container's Postgres
#
# usage: scripts/integration-check.sh
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=$HERE/build/integration
MUSIC=$WORK/music
APP="$HERE/build/Familiar Server.app"
GROUP=~/Library/Group\ Containers/7JL9RZ9C8P.fs
CONTAINER=~/Library/Containers/com.familiar.server
PY=$HERE/build/payload/python/bin/python3
PORT=4400

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then echo "port $PORT is in use" >&2; exit 1; fi
if [ -e "$GROUP/postgres" ]; then echo "$GROUP/postgres exists; refusing to overwrite it" >&2; exit 1; fi

forget_token() { security delete-generic-password -s com.familiar.server.token >/dev/null 2>&1 || true; }
cleanup() {
  forget_token
  pkill -f "Familiar Server.app/Contents/MacOS/FamiliarServer" 2>/dev/null || true
  pkill -f "Familiar Server.app/Contents/Resources/python" 2>/dev/null || true
  pkill -f "Familiar Server.app/Contents/Resources/postgres/bin/postgres" 2>/dev/null || true
  sleep 2
  rm -rf "$GROUP/postgres" "$CONTAINER"
}
trap cleanup EXIT
forget_token

rm -rf "$WORK" && mkdir -p "$MUSIC/Test Artist/Test Album"
"$PY" - "$MUSIC/Test Artist/Test Album/01 Sine.flac" <<'EOF'
import sys, numpy as np, soundfile as sf
sr = 44100
t = np.arange(sr * 40) / sr
tone = 0.3 * np.sin(2 * np.pi * 220 * t) * (1 + 0.5 * np.sin(2 * np.pi * 2 * t))
sf.write(sys.argv[1], np.stack([tone, tone], axis=1), sr, format="FLAC")
EOF
BEFORE=$(find "$MUSIC" -type f -exec shasum {} + | sort | shasum)

echo "==> build (debug, music granted read-only)"
DEV_MUSIC=$MUSIC "$HERE/scripts/build-app.sh" integration >/dev/null

echo "==> Postgres agent"
"$APP/Contents/MacOS/familiar-postgres-agent" &
for _ in $(seq 1 60); do nc -z 127.0.0.1 54329 2>/dev/null && break; sleep 1; done
nc -z 127.0.0.1 54329 || { echo "Postgres did not start"; cat "$GROUP/postgres/postgres.log"; exit 1; }

echo "==> app"
open -n --env FAMILIAR_SERVER_DEV_MUSIC="$MUSIC" --env FAMILIAR_SERVER_DEV_EXTERNAL_POSTGRES=1 "$APP"
for _ in $(seq 1 180); do curl -sf "http://127.0.0.1:$PORT/api/v1/health" >/dev/null && break; sleep 1; done
curl -sf "http://127.0.0.1:$PORT/api/v1/health" >/dev/null || { echo "server did not start"; tail -40 "$CONTAINER/Data/Library/Application Support/Familiar Server/server.log"; exit 1; }
echo "   healthy"

# The app minted the token on first run (ADR-0134 point 2). It keeps it in its own keychain, which
# this script cannot read, so the check reads the server's settings file, and then confirms the
# API refuses a caller without it.
SETTINGS="$CONTAINER/Data/Library/Application Support/Familiar Server/data/settings.json"
for _ in $(seq 1 30); do grep -q access_token "$SETTINGS" 2>/dev/null && break; sleep 1; done
TOKEN=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1])).get('access_token') or '')" "$SETTINGS")
[ -n "$TOKEN" ] || { echo "the app did not mint a token"; exit 1; }
echo "   the app minted the server's token"
ANON=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/v1/tracks")
echo "   anonymous /tracks: $ANON"
[ "$ANON" = "401" ] || exit 1

echo "==> scan and analyse (from inside the sandbox)"
H=(-H "X-Familiar-Token: $TOKEN")
sync() { curl -s "${H[@]}" -X POST "http://127.0.0.1:$PORT/api/v1/library/sync" -H 'content-type: application/json' -d '{}' >/dev/null; }
sync_done() { curl -s "${H[@]}" "http://127.0.0.1:$PORT/api/v1/library/sync/status" | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('status'))"; }
sync
for _ in $(seq 1 60); do [ "$(sync_done)" = "completed" ] && break; sleep 2; done
# Every new file lands in PENDING_REVIEW, and analysis skips it until approved (ADR-0117's review
# flow). Approve as a listener would, then sync again to analyse.
PROFILE=$(curl -s "${H[@]}" -X POST "http://127.0.0.1:$PORT/api/v1/profiles" -H 'content-type: application/json' -d '{"name":"Integration"}' | "$PY" -c "import sys,json;print(json.load(sys.stdin)['id'])")
APPROVED=$(curl -s "${H[@]}" -H "X-Profile-ID: $PROFILE" -X POST "http://127.0.0.1:$PORT/api/v1/pending-tracks/bulk/approve-all" -H 'content-type: application/json' -d '{"queue_analysis": true}')
echo "   approved: $APPROVED"
# Approval does not itself queue analysis (`_queue_for_analysis` is a no-op): the next sync picks
# the track up. The server also starts a sync of its own at launch, so rather than predict which
# sync that will be, ask for one whenever none is running until the track is analysed.
PSQL="$APP/Contents/Resources/postgres/bin/psql"
db() { PGPASSWORD=$(cat "$GROUP/postgres/password") "$PSQL" -h 127.0.0.1 -p 54329 -U familiar -d familiar -Atc "$1"; }
for i in $(seq 1 90); do
  STATE=$(db "select count(*) || ' track(s), ' || (select count(*) from track_analysis where features_version > 0) || ' analysed' from tracks" 2>&1 || true)
  SYNC=$(curl -s "${H[@]}" "http://127.0.0.1:$PORT/api/v1/library/sync/status" | "$PY" -c "import sys,json;d=json.load(sys.stdin);print(d.get('status'), d.get('phase'))" 2>/dev/null || true)
  STATE="$STATE (sync: $SYNC)"
  case "$SYNC" in running*) ;; *) sync ;; esac
  echo "   $STATE"
  case "$STATE" in *" 1 analysed"*) break ;; esac
  sleep 5
done
case "$STATE" in *" 1 analysed"*) echo "   analysis ran inside the sandbox" ;; *) echo "analysis did not complete"; grep -iE "error|semlock|permission" "$CONTAINER/Data/Library/Application Support/Familiar Server/server.log" | tail -20; exit 1 ;; esac

echo "==> zero-touch"
AFTER=$(find "$MUSIC" -type f -exec shasum {} + | sort | shasum)
[ "$BEFORE" = "$AFTER" ] && echo "   the music folder is exactly as it was" || { echo "THE MUSIC FOLDER CHANGED"; find "$MUSIC"; exit 1; }
echo "==> passed"
