#!/bin/bash
# Assemble and sign `Familiar Server.app` (ADR-0136), into desktop/macos/build/.
#
# Signing follows ADR-0136's spike, where each choice was measured:
#   - the app: sandboxed, read-only music, network, the app group     (Support/FamiliarServer.entitlements)
#   - Python and every executable it may run: inherit the app's sandbox (Support/Child.entitlements)
#   - the Postgres agent and Postgres's binaries: unsandboxed, in the app group (Support/Agent.entitlements),
#     because Postgres's System V interlock cannot run in the sandbox
#   - everything with the hardened runtime and no exceptions; all of it signed by one team, so
#     library validation passes for Python's extension modules and onnxruntime
#
# Needs scripts/build-payload.sh first. SIGN_IDENTITY defaults to the first valid Apple Development
# identity; distribution needs a Developer ID Application identity, which the team does not have yet
# (ADR-0135).
#
# usage: scripts/build-app.sh [version]
#        DEV_MUSIC=/path scripts/build-app.sh      debug build that also grants that folder read-only,
#                                                  for scripts/integration-check.sh
set -euo pipefail
CONFIG=release
[ -n "${DEV_MUSIC:-}" ] && CONFIG=debug

HERE=$(cd "$(dirname "$0")/.." && pwd)
VERSION=${1:-dev}
PAYLOAD=$HERE/build/payload
APP="$HERE/build/Familiar Server.app"
SUPPORT=$HERE/Support
ID=${SIGN_IDENTITY:-$(security find-identity -v -p codesigning | grep "Apple Development" | grep -v REVOKED | head -1 | awk '{print $2}')}
[ -n "$ID" ] || { echo "no signing identity" >&2; exit 1; }
[ -x "$PAYLOAD/python/bin/python3" ] || { echo "run scripts/build-payload.sh first" >&2; exit 1; }

echo "==> swift build"
(cd "$HERE" && swift build -c $CONFIG --product FamiliarServer >/dev/null && swift build -c $CONFIG --product familiar-postgres-agent >/dev/null)
BIN=$(cd "$HERE" && swift build -c $CONFIG --show-bin-path)

echo "==> assemble"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Library/LaunchAgents"
cp "$BIN/FamiliarServer" "$BIN/familiar-postgres-agent" "$APP/Contents/MacOS/"
cp "$SUPPORT/com.familiar.server.postgres.plist" "$APP/Contents/Library/LaunchAgents/"
sed -e "s/__VERSION__/$VERSION/" -e "s/__BUILD__/$(date +%Y%m%d%H%M)/" "$SUPPORT/Info.plist" > "$APP/Contents/Info.plist"
cp -R "$PAYLOAD/python" "$PAYLOAD/postgres" "$PAYLOAD/backend" "$PAYLOAD/bin" "$APP/Contents/Resources/"

echo "==> sign with $ID"
sign() { codesign -f -s "$ID" -o runtime --timestamp=none "$@" >/dev/null 2>&1; }
is_macho() { file -b "$1" | grep -q "Mach-O"; }
# 1. Libraries: no entitlements.
find "$APP/Contents/Resources" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 | xargs -0 -n 50 codesign -f -s "$ID" -o runtime --timestamp=none >/dev/null 2>&1
# 2. Postgres's executables: the agent's entitlements. Everything else executable: inherit the sandbox.
find "$APP/Contents/Resources" -type f -perm +111 ! -name "*.dylib" ! -name "*.so" -print0 | while IFS= read -r -d '' f; do
  is_macho "$f" || continue
  case "$f" in
    */Resources/postgres/bin/*) sign --entitlements "$SUPPORT/Agent.entitlements" "$f" ;;
    *) sign --entitlements "$SUPPORT/Child.entitlements" "$f" ;;
  esac
done
# 3. The agent, then the app itself last.
sign --entitlements "$SUPPORT/Agent.entitlements" "$APP/Contents/MacOS/familiar-postgres-agent"
APP_ENTITLEMENTS=$SUPPORT/FamiliarServer.entitlements
if [ -n "${DEV_MUSIC:-}" ]; then
  # The debug integration build stands the test folder in for the picker's read-only grant.
  APP_ENTITLEMENTS=$HERE/build/dev.entitlements
  /usr/libexec/PlistBuddy -x -c "Print" "$SUPPORT/FamiliarServer.entitlements" > "$APP_ENTITLEMENTS"
  /usr/libexec/PlistBuddy -c "Add :com.apple.security.temporary-exception.files.absolute-path.read-only array" \
    -c "Add :com.apple.security.temporary-exception.files.absolute-path.read-only:0 string ${DEV_MUSIC%/}/" "$APP_ENTITLEMENTS"
fi
sign --entitlements "$APP_ENTITLEMENTS" "$APP"
codesign --verify --strict "$APP"
du -sh "$APP"
