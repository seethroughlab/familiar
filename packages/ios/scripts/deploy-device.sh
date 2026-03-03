#!/usr/bin/env bash
set -euo pipefail

# deploy-device.sh — Build and install Familiar directly to a connected iPhone
#
# Usage:
#   ./scripts/deploy-device.sh                    # build + install + launch
#   ./scripts/deploy-device.sh --bump             # also increment build number
#   ./scripts/deploy-device.sh --device <UDID>    # target specific device
#   ./scripts/deploy-device.sh --no-launch        # skip auto-launch after install

# ── Configuration ──────────────────────────────────────────────────────────────

IOS_PKG_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ROOT="$(cd "$IOS_PKG_DIR/../.." && pwd)"
IOS_DIR="$IOS_PKG_DIR/native"
XCODEPROJ="$IOS_DIR/App.xcodeproj"
SCHEME="App"
TEAM_ID="7JL9RZ9C8P"
BUNDLE_ID="com.familiar.player"
EXPORT_OPTIONS="$IOS_PKG_DIR/ExportOptions-dev.plist"
BUILD_DIR="$PROJECT_ROOT/build"
ARCHIVE_PATH="$BUILD_DIR/Familiar.xcarchive"
EXPORT_DIR="$BUILD_DIR/export-dev"
PBXPROJ="$XCODEPROJ/project.pbxproj"

# ── Helpers ────────────────────────────────────────────────────────────────────

red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

die() { red "ERROR: $*" >&2; exit 1; }

step() {
    bold "── $1 ──"
}

# ── Preflight checks ──────────────────────────────────────────────────────────

[[ -f "$PBXPROJ" ]]        || die "Xcode project not found at $PBXPROJ"
[[ -f "$EXPORT_OPTIONS" ]] || die "ExportOptions-dev.plist not found at $EXPORT_OPTIONS"
command -v xcodebuild >/dev/null || die "xcodebuild not found — install Xcode"
command -v xcrun >/dev/null      || die "xcrun not found — install Xcode command line tools"

# ── Parse arguments ────────────────────────────────────────────────────────────

BUMP=false
DEVICE_UDID=""
LAUNCH=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bump)
            BUMP=true
            shift
            ;;
        --device)
            DEVICE_UDID="$2"
            shift 2
            ;;
        --no-launch)
            LAUNCH=false
            shift
            ;;
        *)
            die "Unknown argument: $1\nUsage: $0 [--bump] [--device <UDID>] [--no-launch]"
            ;;
    esac
done

# ── Step 1: Optionally bump build number ─────────────────────────────────────

if $BUMP; then
    step "Bumping build number"
    CURRENT=$(grep -m1 'CURRENT_PROJECT_VERSION' "$PBXPROJ" | sed 's/[^0-9]//g')
    BUILD_NUMBER=$((CURRENT + 1))
    sed -i '' "s/CURRENT_PROJECT_VERSION = [0-9][0-9]*/CURRENT_PROJECT_VERSION = $BUILD_NUMBER/g" "$PBXPROJ"
    green "Build number → $BUILD_NUMBER"
else
    BUILD_NUMBER=$(grep -m1 'CURRENT_PROJECT_VERSION' "$PBXPROJ" | sed 's/[^0-9]//g')
    green "Build number: $BUILD_NUMBER (use --bump to increment)"
fi

# ── Step 2: Build frontend ────────────────────────────────────────────────────

step "Building frontend"

cd "$PROJECT_ROOT"
pnpm --filter @familiar/ios run build:cap
green "Frontend build complete"

# ── Step 3: Capacitor sync ────────────────────────────────────────────────────

step "Syncing Capacitor"

cd "$IOS_PKG_DIR"
# Use cap copy (not sync) — native deps managed by SPM, not CocoaPods
npx cap copy ios

# cap copy regenerates capacitor.config.json but doesn't copy packageClassList
# from the TS config. Re-add local plugins that aren't in npm packages.
CAP_CONFIG="$IOS_DIR/App/App/capacitor.config.json"
if ! grep -q 'FamiliarAudioPlugin' "$CAP_CONFIG"; then
    sed -i '' 's/"PreferencesPlugin"/"PreferencesPlugin",\
\t\t"FamiliarAudioPlugin"/' "$CAP_CONFIG"
    green "Re-added FamiliarAudioPlugin to native config"
fi

# cap copy writes to native/App/App/ (Capacitor's standard double-nesting),
# but this project's Xcode layout reads from native/App/ (single nesting).
# Sync the web assets to where Xcode actually bundles them.
rsync -a --delete "$IOS_DIR/App/App/public/" "$IOS_DIR/App/public/"
cp "$IOS_DIR/App/App/capacitor.config.json" "$IOS_DIR/App/capacitor.config.json"
green "Synced web assets to Xcode bundle directory"

green "Capacitor sync complete"

# ── Step 4: Xcode archive ─────────────────────────────────────────────────────

step "Archiving (this takes a minute)"

mkdir -p "$BUILD_DIR"

xcodebuild archive \
    -project "$XCODEPROJ" \
    -scheme "$SCHEME" \
    -destination "generic/platform=iOS" \
    -archivePath "$ARCHIVE_PATH" \
    CODE_SIGN_STYLE=Automatic \
    DEVELOPMENT_TEAM="$TEAM_ID" \
    -quiet

green "Archive complete → $ARCHIVE_PATH"

# ── Step 5: Export IPA (development) ─────────────────────────────────────────

step "Exporting IPA (development signing)"

rm -rf "$EXPORT_DIR"

xcodebuild -exportArchive \
    -archivePath "$ARCHIVE_PATH" \
    -exportPath "$EXPORT_DIR" \
    -exportOptionsPlist "$EXPORT_OPTIONS" \
    -quiet

IPA_PATH="$EXPORT_DIR/App.ipa"
[[ -f "$IPA_PATH" ]] || die "IPA not found at $IPA_PATH — export may have failed"

green "Export complete → $IPA_PATH"

# ── Step 6: Detect connected device ─────────────────────────────────────────

step "Finding connected device"

if [[ -n "$DEVICE_UDID" ]]; then
    green "Using specified device: $DEVICE_UDID"
else
    # List connected devices and grab the first iPhone UDID
    DEVICE_JSON=$(xcrun devicectl list devices --json-output /dev/stdout 2>/dev/null || true)

    if [[ -z "$DEVICE_JSON" ]]; then
        die "No device output from devicectl. Is a device connected via USB?"
    fi

    # Extract first connected device UDID
    DEVICE_UDID=$(echo "$DEVICE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
devices = data.get('result', {}).get('devices', [])
for d in devices:
    conn = d.get('connectionProperties', {})
    if conn.get('transportType') == 'wired':
        print(d['identifier'])
        sys.exit(0)
# Fall back to any device if no wired device found
for d in devices:
    print(d['identifier'])
    sys.exit(0)
sys.exit(1)
" 2>/dev/null) || die "No connected device found. Connect an iPhone via USB and try again."

    DEVICE_NAME=$(echo "$DEVICE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
devices = data.get('result', {}).get('devices', [])
for d in devices:
    if d['identifier'] == '$DEVICE_UDID':
        print(d.get('deviceProperties', {}).get('name', 'Unknown'))
        sys.exit(0)
" 2>/dev/null) || DEVICE_NAME="Unknown"

    green "Found device: $DEVICE_NAME ($DEVICE_UDID)"
fi

# ── Step 7: Install app on device ────────────────────────────────────────────

step "Installing on device"

xcrun devicectl device install app \
    --device "$DEVICE_UDID" \
    "$IPA_PATH"

green "App installed!"

# ── Step 8: Optionally launch app ────────────────────────────────────────────

if $LAUNCH; then
    step "Launching app"
    xcrun devicectl device process launch \
        --device "$DEVICE_UDID" \
        "$BUNDLE_ID" || green "Launch failed — open the app manually"
    green "App launched!"
fi

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
bold "Build $BUILD_NUMBER installed on device."
