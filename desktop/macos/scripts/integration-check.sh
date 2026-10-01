#!/bin/bash
# End-to-end check of the assembled app (ADR-0136, ADR-0140): the real bundle, as it really starts.
#
#   1. a folder with a 40-second FLAC and an AIFF, writable by whoever runs this, as a real library is
#   2. the app launched in its debug integration mode (no folder picker), registering its Postgres
#      agent with SMAppService itself: the step ADR-0136 never exercised, and the one that failed
#      on the first real install (ADR-0140 Context)
#   3. the server comes up at all, which proves the Seatbelt profile is on: the folder is writable,
#      and the backend refuses to start on a folder it could write unless the profile makes
#      `os.access` say otherwise (ADR-0140 point 3)
#   4. it mints its own token, scans the tracks and analyses them, with no approval (a first import
#      arrives active)
#   5. ffmpeg (cover extraction, AAC) and libchromaprint (fingerprints) work under the profile
#   6. the music folder is exactly as it was
#   7. everything stopped and removed: the agent unregistered, the app's data, Postgres's data
#
# usage: scripts/integration-check.sh
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=$HERE/build/integration
MUSIC=$WORK/music
APP="$HERE/build/Familiar Server.app"
GROUP=~/Library/Group\ Containers/7JL9RZ9C8P.fs
SUPPORT=~/Library/Application\ Support/Familiar\ Server
PY=$HERE/build/payload/python/bin/python3
PORT=4400

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then echo "port $PORT is in use" >&2; exit 1; fi
if [ -e "$GROUP/postgres" ]; then echo "$GROUP/postgres exists; refusing to overwrite it" >&2; exit 1; fi
if [ -e "$SUPPORT" ]; then echo "$SUPPORT exists (an installed Familiar Server's data); refusing to remove it" >&2; exit 1; fi

forget_token() { security delete-generic-password -s com.familiar.server.token >/dev/null 2>&1 || true; }
cleanup() {
  forget_token
  # Unregister the agent, or launchd starts it again at the next login, from this build folder.
  [ -d "$APP" ] && open -W -n --env FAMILIAR_SERVER_DEV_UNREGISTER=1 "$APP" 2>/dev/null || true
  pkill -f "Familiar Server.app/Contents/MacOS/FamiliarServer" 2>/dev/null || true
  pkill -f "Familiar Server.app/Contents/Resources/python" 2>/dev/null || true
  pkill -f "Familiar Server.app/Contents/Resources/postgres/bin/postgres" 2>/dev/null || true
  sleep 2
  rm -rf "$GROUP/postgres" "$SUPPORT"
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
# An AIFF with an attached cover: for AIFF and WAV the backend extracts covers with ffmpeg
# (mutagen covers FLAC, MP3 and M4A), so this is what exercises the bundled ffmpeg under the
# profile. Made with that same ffmpeg, outside it.
FF=$HERE/build/payload/bin/ffmpeg
"$FF" -hide_banner -loglevel error -f lavfi -i "color=c=0x6644aa:s=300x300" -frames:v 1 "$WORK/cover.jpg"
"$FF" -hide_banner -loglevel error -i "$MUSIC/Test Artist/Test Album/01 Sine.flac" -i "$WORK/cover.jpg" \
  -map 0:a -map 1 -c:a pcm_s16be -c:v copy -disposition:v attached_pic -write_id3v2 1 \
  "$MUSIC/Test Artist/Test Album/02 Cover.aiff"
BEFORE=$(find "$MUSIC" -type f -exec shasum {} + | sort | shasum)

echo "==> build (debug)"
DEV_MUSIC=$MUSIC "$HERE/scripts/build-app.sh" integration >/dev/null
[ -w "$MUSIC" ] || { echo "the test library must be writable, or step 3 proves nothing" >&2; exit 1; }

echo "==> app, registering its own Postgres agent"
open -n --env FAMILIAR_SERVER_DEV_MUSIC="$MUSIC" "$APP"
for _ in $(seq 1 90); do nc -z 127.0.0.1 54329 2>/dev/null && break; sleep 1; done
nc -z 127.0.0.1 54329 || { echo "Postgres did not start"; tail -20 "$SUPPORT/server.log" 2>/dev/null; cat "$GROUP/postgres/postgres.log" 2>/dev/null; exit 1; }
launchctl print "gui/$(id -u)/com.familiar.server.postgres" >/dev/null 2>&1 \
  || { echo "Postgres is up, but not as the registered agent"; exit 1; }
echo "   registered with SMAppService, started by launchd"
for _ in $(seq 1 180); do curl -sf "http://127.0.0.1:$PORT/api/v1/health" >/dev/null && break; sleep 1; done
curl -sf "http://127.0.0.1:$PORT/api/v1/health" >/dev/null || { echo "server did not start"; tail -40 "$SUPPORT/server.log"; exit 1; }
echo "   healthy, on a library its owner can write: the zero-touch profile is on"

# The app minted the token on first run (ADR-0134 point 2). It keeps it in its own keychain, which
# this script cannot read, so the check reads the server's settings file, and then confirms the
# API refuses a caller without it.
SETTINGS="$SUPPORT/data/settings.json"
for _ in $(seq 1 30); do grep -q access_token "$SETTINGS" 2>/dev/null && break; sleep 1; done
TOKEN=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1])).get('access_token') or '')" "$SETTINGS")
[ -n "$TOKEN" ] || { echo "the app did not mint a token"; exit 1; }
echo "   the app minted the server's token"
ANON=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/v1/tracks")
echo "   anonymous /tracks: $ANON"
[ "$ANON" = "401" ] || exit 1

echo "==> scan and analyse (under the zero-touch profile)"
H=(-H "X-Familiar-Token: $TOKEN")
sync() { curl -s "${H[@]}" -X POST "http://127.0.0.1:$PORT/api/v1/library/sync" -H 'content-type: application/json' -d '{}' >/dev/null; }
sync_done() { curl -s "${H[@]}" "http://127.0.0.1:$PORT/api/v1/library/sync/status" | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('status'))"; }
# No approval step: on a fresh server this is the library's first import, so the track arrives
# active and is analysed without anyone reviewing it. A coworker's first run depends on exactly
# this. Ask for a sync whenever none is running (the server also starts one itself at launch).
PSQL="$APP/Contents/Resources/postgres/bin/psql"
db() { PGPASSWORD=$(cat "$GROUP/postgres/password") "$PSQL" -h 127.0.0.1 -p 54329 -U familiar -d familiar -Atc "$1"; }
for i in $(seq 1 90); do
  STATE=$(db "select count(*) || ' track(s), ' || (select count(*) from track_analysis where features_version > 0) || ' analysed' from tracks" 2>&1 || true)
  SYNC=$(curl -s "${H[@]}" "http://127.0.0.1:$PORT/api/v1/library/sync/status" | "$PY" -c "import sys,json;d=json.load(sys.stdin);print(d.get('status'), d.get('phase'))" 2>/dev/null || true)
  STATE="$STATE (sync: $SYNC)"
  case "$SYNC" in running*) ;; *) sync ;; esac
  echo "   $STATE"
  case "$STATE" in *" 2 analysed"*) break ;; esac
  sleep 5
done
case "$STATE" in *" 2 analysed"*) echo "   analysis ran under the profile, as a first import: status $(db "select string_agg(distinct status::text, ',') from tracks")" ;; *) echo "analysis did not complete"; grep -iE "error|semlock|permission" "$SUPPORT/server.log" | tail -20; exit 1 ;; esac

echo "==> ffmpeg, under the profile"
FLAC_ID=$(db "select id from tracks where file_path like '%01 Sine.flac'")
AIFF_ID=$(db "select id from tracks where file_path like '%02 Cover.aiff'")
ART=$(curl -s "${H[@]}" -o "$WORK/art.out" -w '%{http_code} %{content_type}' "http://127.0.0.1:$PORT/api/v1/tracks/$AIFF_ID/artwork")
echo "   AIFF cover (ffmpeg extraction): $ART, $(file -b "$WORK/art.out" | cut -c1-40)"
case "$ART" in 200\ image/*) ;; *) echo "cover extraction failed"; exit 1 ;; esac
AAC=$(curl -s "${H[@]}" -o "$WORK/aac.out" -w '%{http_code} %{content_type}' "http://127.0.0.1:$PORT/api/v1/tracks/$FLAC_ID/stream?format=aac")
echo "   FLAC as AAC (ffmpeg encode, ADR-0118): $AAC, $(wc -c < "$WORK/aac.out" | tr -d ' ') bytes, $("$HERE/build/payload/bin/ffprobe" -v error -show_entries stream=codec_name -of csv=p=0 "$WORK/aac.out")"
case "$AAC" in 200\ audio/*) ;; *) echo "AAC encode failed"; exit 1 ;; esac

echo "==> AcoustID fingerprints, under the profile"
# The bundled libchromaprint, loaded by path, decoding with the bundled ffmpeg: the Docker image's
# path, not fpcalc's (analysis._FINGERPRINT_CHILD). The same child run outside the profile must
# produce the same string, or the profile changed the decode.
FPS=$(db "select count(*) from track_analysis where acoustid is not null")
echo "   stored: $FPS of 2"
[ "$FPS" = "2" ] || { grep -i "fingerprint" "$SUPPORT/server.log" | tail -5; exit 1; }
STORED=$(db "select a.acoustid from track_analysis a join tracks t on t.id = a.track_id where t.file_path like '%01 Sine.flac'")
OUTSIDE=$(cd "$HERE/build/payload/backend" && PATH="$HERE/build/payload/bin:/usr/bin:/bin" \
  FAMILIAR_CHROMAPRINT_LIBRARY="$HERE/build/payload/lib/libchromaprint.1.dylib" "$PY" -c \
  "import ast,sys; tree=ast.parse(open('app/services/analysis.py').read()); ns={}; exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') in ('_IMPORT_ACOUSTID', '_FINGERPRINT_CHILD')], []), 'analysis', 'exec'), ns); sys.argv=['-c', sys.argv[1]]; exec(ns['_FINGERPRINT_CHILD'])" \
  "$MUSIC/Test Artist/Test Album/01 Sine.flac" | "$PY" -c "import sys,json;print(json.load(sys.stdin)[1])")
[ "$STORED" = "$OUTSIDE" ] && echo "   identical to the same child run outside the profile" || { echo "fingerprints differ"; exit 1; }

echo "==> quit as macOS quits it (logout, the Dock), not by the menu"
osascript -e 'tell application id "com.familiar.server" to quit' >/dev/null
for _ in $(seq 1 30); do pgrep -f "Familiar Server.app/Contents/Resources/python" >/dev/null || break; sleep 1; done
if pgrep -f "Familiar Server.app/Contents/Resources/python" >/dev/null; then
  echo "the server outlived the app"; exit 1
fi
echo "   the server stopped with the app"

echo "==> zero-touch"
AFTER=$(find "$MUSIC" -type f -exec shasum {} + | sort | shasum)
[ "$BEFORE" = "$AFTER" ] && echo "   the music folder is exactly as it was" || { echo "THE MUSIC FOLDER CHANGED"; find "$MUSIC"; exit 1; }
echo "==> passed"
