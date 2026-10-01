#!/bin/bash
# Assemble and sign `Familiar Server.app` (ADR-0136, ADR-0140), into desktop/macos/build/.
#
# Nothing is App-Sandboxed (ADR-0140): a sandboxed app cannot register the unsandboxed agent Postgres
# needs. The music stays unwritten because the server runs under a Seatbelt profile (ServerLaunch).
#   - the app and the Postgres agent: no entitlements    (Support/FamiliarServer.entitlements, Agent.entitlements)
#   - Python and every executable it runs: numba's executable-memory exception only (Support/Child.entitlements)
#   - everything with the hardened runtime; all of it signed by one team, so library validation
#     passes for Python's extension modules and onnxruntime
#
# Needs scripts/build-payload.sh first. SIGN_IDENTITY defaults to the first valid Apple Development
# identity. A distributed build is signed with the team's Developer ID Application identity
# (ADR-0135), and then every signature carries a secure timestamp, which notarization requires;
# development builds skip it, since it is a network round trip for each of ~450 binaries.
# scripts/package.sh turns a Developer ID build into a notarized .dmg.
#
# usage: scripts/build-app.sh [tag]         the release tag; the bundle's version drops its `v`
#        DEV_MUSIC=/path scripts/build-app.sh      debug build, which honours the development switches
#                                                  scripts/integration-check.sh uses
set -euo pipefail
# Native arm64 only. Under Rosetta — the x86_64 GitHub runner on an Apple Silicon Mac — every
# child would build for Intel: ffmpeg probes for x86 assembly and the Swift binaries come out
# x86_64 beside an arm64 Python. So re-run natively, and refuse a real Intel Mac outright.
if [ "$(uname -m)" != arm64 ]; then
  if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = 1 ]; then exec arch -arm64 /bin/bash "$0" "$@"; fi
  echo "Familiar Server is built on Apple Silicon; this machine is $(uname -m)" >&2; exit 1
fi
CONFIG=release
[ -n "${DEV_MUSIC:-}" ] && CONFIG=debug

HERE=$(cd "$(dirname "$0")/.." && pwd)
VERSION=${1:-dev}
PAYLOAD=$HERE/build/payload
APP="$HERE/build/Familiar Server.app"
SUPPORT=$HERE/Support
ID=${SIGN_IDENTITY:-$(security find-identity -v -p codesigning | grep "Apple Development" | grep -v REVOKED | head -1 | awk '{print $2}')}
[ -n "$ID" ] || { echo "no signing identity" >&2; exit 1; }
TIMESTAMP=--timestamp=none
if security find-identity -v -p codesigning | grep -F "$ID" | grep -q "Developer ID Application"; then
  TIMESTAMP=--timestamp
fi
[ -x "$PAYLOAD/python/bin/python3" ] || { echo "run scripts/build-payload.sh first" >&2; exit 1; }

echo "==> swift build"
(cd "$HERE" && swift build -c $CONFIG --product FamiliarServer >/dev/null && swift build -c $CONFIG --product familiar-postgres-agent >/dev/null)
BIN=$(cd "$HERE" && swift build -c $CONFIG --show-bin-path)

echo "==> assemble"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Library/LaunchAgents" "$APP/Contents/Frameworks"
cp "$BIN/FamiliarServer" "$BIN/familiar-postgres-agent" "$APP/Contents/MacOS/"
cp "$SUPPORT/com.familiar.server.postgres.plist" "$APP/Contents/Library/LaunchAgents/"
# A debug build is the integration check's, and gets an identity of its own: its own bundle id (so
# macOS's background-items record for an installed Familiar Server never judges it, and the reverse),
# its own agent label (so the two agents never collide in launchd), and so its own data folder
# (Layout.defaultAppSupport). Found 2026-10-01: a record left by sandboxed builds, keyed by bundle
# id, kept "sandboxed" through unregistering, and refused every later build's agent.
INTEGRATION_ID=com.familiar.server.integration
# Updates (ADR-0135 point 3). ditto keeps the framework's Versions/ symlinks, which cp -R would not.
ditto "$BIN/Sparkle.framework" "$APP/Contents/Frameworks/Sparkle.framework"
sed -e "s/__VERSION__/${VERSION#v}/" -e "s/__BUILD__/$(date +%Y%m%d%H%M)/" "$SUPPORT/Info.plist" > "$APP/Contents/Info.plist"
if [ "$CONFIG" = debug ]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $INTEGRATION_ID" "$APP/Contents/Info.plist"
  AGENT_PLIST="$APP/Contents/Library/LaunchAgents/com.familiar.server.postgres.plist"
  /usr/libexec/PlistBuddy -c "Set :Label $INTEGRATION_ID.postgres" -c "Set :AssociatedBundleIdentifiers:0 $INTEGRATION_ID" "$AGENT_PLIST"
fi
cp -R "$PAYLOAD/python" "$PAYLOAD/postgres" "$PAYLOAD/backend" "$PAYLOAD/bin" "$PAYLOAD/lib" "$APP/Contents/Resources/"

echo "==> sign with $ID ($TIMESTAMP)"
sign() {
  local out
  out=$(codesign -f -s "$ID" -o runtime "$TIMESTAMP" "$@" 2>&1) || { echo "$out" >&2; return 1; }
}
is_macho() { file -b "$1" | grep -q "Mach-O"; }
# 1. Libraries: no entitlements.
find "$APP/Contents/Resources" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 \
  | xargs -0 -n 50 -P 4 codesign -f -s "$ID" -o runtime "$TIMESTAMP" 2>&1 | grep -v "replacing existing signature" >&2 || true
# xargs hides a failure behind grep; ask each library instead.
find "$APP/Contents/Resources" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 \
  | xargs -0 -n 200 codesign --verify --strict
# 2. Postgres's executables: the agent's entitlements. Everything else executable: the child's.
find "$APP/Contents/Resources" -type f -perm +111 ! -name "*.dylib" ! -name "*.so" -print0 | while IFS= read -r -d '' f; do
  is_macho "$f" || continue
  case "$f" in
    */Resources/postgres/bin/*) sign --entitlements "$SUPPORT/Agent.entitlements" "$f" ;;
    *) sign --entitlements "$SUPPORT/Child.entitlements" "$f" ;;
  esac
done
# 3. Sparkle, inside out, as its sandboxing guide orders it: the XPC services (the downloader keeps
#    its own entitlements), the installer, the updater, then the framework.
SPARKLE="$APP/Contents/Frameworks/Sparkle.framework/Versions/B"
sign "$SPARKLE/XPCServices/Installer.xpc"
sign --preserve-metadata=entitlements "$SPARKLE/XPCServices/Downloader.xpc"
sign "$SPARKLE/Autoupdate"
sign "$SPARKLE/Updater.app"
sign "$APP/Contents/Frameworks/Sparkle.framework"
# 4. The agent, then the app itself last.
sign --entitlements "$SUPPORT/Agent.entitlements" "$APP/Contents/MacOS/familiar-postgres-agent"
sign --entitlements "$SUPPORT/FamiliarServer.entitlements" "$APP"
codesign --verify --deep --strict "$APP"
du -sh "$APP"
