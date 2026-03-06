#!/usr/bin/env bash
set -euo pipefail

# release-testflight.sh — Build and upload Familiar to TestFlight
#
# Usage:
#   ./scripts/release-testflight.sh             # auto-increment build number
#   ./scripts/release-testflight.sh --build 5   # set specific build number

# ── Configuration ──────────────────────────────────────────────────────────────

IOS_PKG_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ROOT="$(cd "$IOS_PKG_DIR/../.." && pwd)"
IOS_DIR="$IOS_PKG_DIR/native"
XCODEPROJ="$IOS_DIR/App.xcodeproj"
SCHEME="App"
TEAM_ID="7JL9RZ9C8P"
API_KEY_ID="3CLXK2R8N9"
API_ISSUER_ID="69a6de88-18db-47e3-e053-5b8c7c11a4d1"
P8_KEY_PATH="$PROJECT_ROOT/AuthKey_${API_KEY_ID}.p8"
EXPORT_OPTIONS="$IOS_PKG_DIR/ExportOptions.plist"
BUILD_DIR="$PROJECT_ROOT/build"
ARCHIVE_PATH="$BUILD_DIR/Familiar.xcarchive"
EXPORT_DIR="$BUILD_DIR/export"
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

[[ -f "$PBXPROJ" ]]      || die "Xcode project not found at $PBXPROJ"
[[ -f "$P8_KEY_PATH" ]]  || die "API key not found at $P8_KEY_PATH"
[[ -f "$EXPORT_OPTIONS" ]] || die "ExportOptions.plist not found at $EXPORT_OPTIONS"
command -v xcodebuild >/dev/null || die "xcodebuild not found — install Xcode"

# ── Parse arguments ────────────────────────────────────────────────────────────

BUILD_NUMBER=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --build)
            BUILD_NUMBER="$2"
            shift 2
            ;;
        *)
            die "Unknown argument: $1"
            ;;
    esac
done

# ── Step 1: Bump build number ─────────────────────────────────────────────────

step "Bumping build number"

if [[ -z "$BUILD_NUMBER" ]]; then
    # Read current build number and increment
    CURRENT=$(grep -m1 'CURRENT_PROJECT_VERSION' "$PBXPROJ" | sed 's/[^0-9]//g')
    BUILD_NUMBER=$((CURRENT + 1))
fi

# Update all occurrences in project.pbxproj
sed -i '' "s/CURRENT_PROJECT_VERSION = [0-9][0-9]*/CURRENT_PROJECT_VERSION = $BUILD_NUMBER/g" "$PBXPROJ"
green "Build number → $BUILD_NUMBER"

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
    -allowProvisioningUpdates \
    -quiet

green "Archive complete → $ARCHIVE_PATH"

# ── Step 5: Export IPA ─────────────────────────────────────────────────────────

step "Exporting IPA"

xcodebuild -exportArchive \
    -archivePath "$ARCHIVE_PATH" \
    -exportPath "$EXPORT_DIR" \
    -exportOptionsPlist "$EXPORT_OPTIONS" \
    -allowProvisioningUpdates \
    -quiet

green "Export + upload complete!"
echo ""
bold "Build $BUILD_NUMBER uploaded to TestFlight."
bold "Check App Store Connect for processing status."
