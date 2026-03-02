#!/usr/bin/env bash
set -euo pipefail

# release-testflight.sh — Build and upload Familiar to TestFlight
#
# Usage:
#   ./dev/scripts/release-testflight.sh             # auto-increment build number
#   ./dev/scripts/release-testflight.sh --build 5   # set specific build number

# ── Configuration ──────────────────────────────────────────────────────────────

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
IOS_DIR="$FRONTEND_DIR/ios"
XCODEPROJ="$IOS_DIR/App/App.xcodeproj"
SCHEME="App"
TEAM_ID="7JL9RZ9C8P"
API_KEY_ID="3CLXK2R8N9"
API_ISSUER_ID="69a6de88-18db-47e3-e053-5b8c7c11a4d1"
P8_KEY_PATH="$PROJECT_ROOT/AuthKey_${API_KEY_ID}.p8"
EXPORT_OPTIONS="$IOS_DIR/ExportOptions.plist"
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
command -v xcrun >/dev/null      || die "xcrun not found — install Xcode CLI tools"

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

cd "$FRONTEND_DIR"
npm run build:cap
green "Frontend build complete"

# ── Step 3: Capacitor sync ────────────────────────────────────────────────────

step "Syncing Capacitor"

npx cap sync ios
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

# ── Step 5: Export IPA ─────────────────────────────────────────────────────────

step "Exporting IPA"

xcodebuild -exportArchive \
    -archivePath "$ARCHIVE_PATH" \
    -exportPath "$EXPORT_DIR" \
    -exportOptionsPlist "$EXPORT_OPTIONS" \
    -quiet

IPA_PATH=$(find "$EXPORT_DIR" -name "*.ipa" -print -quit)
[[ -n "$IPA_PATH" ]] || die "No IPA found in $EXPORT_DIR"
green "IPA exported → $IPA_PATH"

# ── Step 6: Upload to TestFlight ───────────────────────────────────────────────

step "Uploading to TestFlight"

# altool searches for AuthKey in specific directories — ensure it's available
ALTOOL_KEY_DIR="$HOME/.private_keys"
mkdir -p "$ALTOOL_KEY_DIR"
if [[ ! -f "$ALTOOL_KEY_DIR/AuthKey_${API_KEY_ID}.p8" ]]; then
    cp "$P8_KEY_PATH" "$ALTOOL_KEY_DIR/AuthKey_${API_KEY_ID}.p8"
fi

xcrun altool --upload-app \
    --type ios \
    --file "$IPA_PATH" \
    --apiKey "$API_KEY_ID" \
    --apiIssuer "$API_ISSUER_ID"

green "Upload complete!"
echo ""
bold "Build $BUILD_NUMBER uploaded to TestFlight."
bold "Check App Store Connect for processing status."
