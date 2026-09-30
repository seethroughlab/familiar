#!/bin/bash
# Turn a Developer ID build of `Familiar Server.app` into a notarized, stapled .dmg (ADR-0135 point 1),
# at desktop/macos/build/Familiar-Server-<version>.dmg, <version> being the tag without its `v`.
#
#   1. refuse an app not signed with a Developer ID Application identity (notarization would refuse it
#      later and slower)
#   2. a .dmg holding the app and an Applications link, signed with the same identity
#   3. notarized by the App Store Connect API key, waiting for Apple's answer; on anything but
#      Accepted, Apple's log is printed and the script fails
#   4. the ticket stapled to the .dmg, so it opens offline
#   5. checked as Gatekeeper checks a download: the .dmg, and the app inside it, must assess as
#      "Notarized Developer ID"
#
# The key is the one familiar-apple's App Store uploads use; notarytool accepts the same kind:
#   NOTARY_KEY_ID      the key's id                       (e.g. 3CLXK2R8N9)
#   NOTARY_ISSUER_ID   the team's App Store Connect issuer id
#   NOTARY_KEY_PATH    the .p8 file; defaults to ~/.appstoreconnect/private_keys/AuthKey_<id>.p8
#
# usage: scripts/build-payload.sh <tag>, scripts/build-app.sh <tag> (with SIGN_IDENTITY set to the
#        Developer ID), then scripts/package.sh <tag>
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
TAG=${1:?usage: scripts/package.sh <tag>}
VERSION=${TAG#v}
APP="$HERE/build/Familiar Server.app"
DMG="$HERE/build/Familiar-Server-$VERSION.dmg"
: "${NOTARY_KEY_ID:?set NOTARY_KEY_ID}" "${NOTARY_ISSUER_ID:?set NOTARY_ISSUER_ID}"
NOTARY_KEY_PATH=${NOTARY_KEY_PATH:-$HOME/.appstoreconnect/private_keys/AuthKey_$NOTARY_KEY_ID.p8}
[ -f "$NOTARY_KEY_PATH" ] || { echo "no notary key at $NOTARY_KEY_PATH" >&2; exit 1; }

echo "==> check the app's signature"
# Read whole, then searched: `grep -m1` closing the pipe early is a SIGPIPE, fatal under pipefail.
SIGNATURE=$(codesign -dvv "$APP" 2>&1)
AUTHORITY=$(printf '%s\n' "$SIGNATURE" | awk 'sub(/^Authority=/, "") && !found { print; found = 1 }')
case "$AUTHORITY" in
  "Developer ID Application: "*) echo "   $AUTHORITY" ;;
  *) echo "the app is signed by '$AUTHORITY', not a Developer ID Application identity;" \
       "rebuild with SIGN_IDENTITY set to it" >&2; exit 1 ;;
esac
codesign --verify --deep --strict "$APP"
PLIST_VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")
[ "$PLIST_VERSION" = "$VERSION" ] || { echo "the app is version $PLIST_VERSION, not $VERSION" >&2; exit 1; }

echo "==> dmg"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -quiet -volname "Familiar Server" -srcfolder "$STAGE" -fs APFS -format ULFO "$DMG"
codesign -s "$AUTHORITY" --timestamp "$DMG"
echo "   $(du -h "$DMG" | cut -f1) $DMG"

echo "==> notarize (Apple's answer usually takes minutes)"
RESULT=$(xcrun notarytool submit "$DMG" --key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" \
  --issuer "$NOTARY_ISSUER_ID" --wait --timeout 2h --output-format json)
SUBMISSION=$(echo "$RESULT" | /usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
STATUS=$(echo "$RESULT" | /usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
echo "   submission $SUBMISSION: $STATUS"
if [ "$STATUS" != "Accepted" ]; then
  xcrun notarytool log "$SUBMISSION" --key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" \
    --issuer "$NOTARY_ISSUER_ID" >&2
  exit 1
fi

echo "==> staple"
xcrun stapler staple -q "$DMG"
xcrun stapler validate -q "$DMG"

echo "==> assess, as Gatekeeper will"
spctl --assess --type open --context context:primary-signature -vv "$DMG" 2>&1 | sed 's/^/   /'
MOUNT=$(mktemp -d)
hdiutil attach -quiet -nobrowse -readonly -mountpoint "$MOUNT" "$DMG"
ASSESS=$(spctl --assess --type execute -vv "$MOUNT/Familiar Server.app" 2>&1 || true)
hdiutil detach -quiet "$MOUNT"
echo "$ASSESS" | sed 's/^/   /'
echo "$ASSESS" | grep -q "source=Notarized Developer ID" || { echo "the app does not assess as notarized" >&2; exit 1; }
echo "==> $DMG"
