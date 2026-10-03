#!/bin/bash
# Publish a notarized Familiar Server .dmg to the Sparkle feed (ADR-0135 point 3).
#
#   1. sign the .dmg with the update key, using Sparkle's own sign_update (pinned, checksum-verified)
#   2. check the signature verifies against the public key the app carries in Support/Info.plist —
#      a key that does not match would publish an update every installed copy refuses
#   3. add the release to appcast.xml on the `appcast` branch and push it
#
# Run after the .dmg is attached to the release: the feed must never name a file not yet there.
#
# usage: scripts/publish-update.sh <tag> <ed-private-key-file>
#        DRY_RUN=1 …   everything but the push; prints the feed instead
set -euo pipefail

SPARKLE_VERSION=2.10.0
SPARKLE_SHA256=c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c

HERE=$(cd "$(dirname "$0")/.." && pwd)
REPO=$(cd "$HERE/../.." && pwd)
TAG=${1:?usage: scripts/publish-update.sh <tag> <ed-private-key-file>}
KEY=${2:?usage: scripts/publish-update.sh <tag> <ed-private-key-file>}
VERSION=${TAG#v}
APP="$HERE/build/Familiar Server.app"
DMG="$HERE/build/Familiar-Server-$VERSION.dmg"
[ -f "$DMG" ] || { echo "no $DMG; run scripts/package.sh $TAG first" >&2; exit 1; }

echo "==> Sparkle $SPARKLE_VERSION tools"
TOOLS="$HERE/build/sparkle-$SPARKLE_VERSION"
if [ ! -x "$TOOLS/bin/sign_update" ]; then
  mkdir -p "$TOOLS"
  curl -sfL -o "$TOOLS.tar.xz" \
    "https://github.com/sparkle-project/Sparkle/releases/download/$SPARKLE_VERSION/Sparkle-$SPARKLE_VERSION.tar.xz"
  echo "$SPARKLE_SHA256  $TOOLS.tar.xz" | shasum -a 256 -c --quiet
  tar xf "$TOOLS.tar.xz" -C "$TOOLS"
fi

echo "==> sign"
SIGNED=$("$TOOLS/bin/sign_update" --ed-key-file "$KEY" "$DMG")   # sparkle:edSignature="…" length="…"
SIGNATURE=$(sed -n 's/.*sparkle:edSignature="\([^"]*\)".*/\1/p' <<< "$SIGNED")
LENGTH=$(sed -n 's/.*length="\([0-9]*\)".*/\1/p' <<< "$SIGNED")
[ -n "$SIGNATURE" ] && [ -n "$LENGTH" ] || { echo "sign_update said: $SIGNED" >&2; exit 1; }
"$TOOLS/bin/sign_update" --verify --ed-key-file "$KEY" "$DMG" "$SIGNATURE" >/dev/null
# The key is a 32-byte Ed25519 seed; its public half, derived with OpenSSL 3 (macOS's LibreSSL has no
# Ed25519), must be the SUPublicEDKey the app carries, or every installed copy refuses the update.
OPENSSL=/opt/homebrew/bin/openssl
[ -x "$OPENSSL" ] || OPENSSL=openssl
PUBLIC=$(/usr/libexec/PlistBuddy -c "Print :SUPublicEDKey" "$HERE/Support/Info.plist")
DERIVED=$({ printf '302e020100300506032b657004220420' | xxd -r -p; base64 -d < "$KEY"; } \
  | "$OPENSSL" pkey -inform DER -pubout -outform DER | tail -c 32 | base64)
[ "$DERIVED" = "$PUBLIC" ] || { echo "the update key's public half is $DERIVED; the app carries $PUBLIC" >&2; exit 1; }
BUILD=$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$APP/Contents/Info.plist")
SHIPPED=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist")
[ "$SHIPPED" = "$VERSION" ] || { echo "the app is $SHIPPED, not $VERSION" >&2; exit 1; }

echo "==> appcast branch"
FEED=$(mktemp -d)
trap 'git -C "$REPO" worktree remove --force "$FEED" 2>/dev/null || rm -rf "$FEED"' EXIT
if git -C "$REPO" fetch -q origin appcast 2>/dev/null; then
  git -C "$REPO" worktree add -q --detach "$FEED" FETCH_HEAD
else
  # The first release: a branch with no history and nothing in it but the feed. `switch --orphan`
  # empties the index and the working tree; `checkout --orphan` keeps every file of the source.
  git -C "$REPO" worktree add -q --detach "$FEED"
  git -C "$FEED" switch -q --orphan appcast-new
fi
# --notes: each entry's notes are its CHANGELOG.md section, not a link to the release page, which
# Sparkle's notes pane showed as GitHub's header (appcast.py's docstring).
python3 "$HERE/scripts/appcast.py" "$FEED/appcast.xml" \
  --tag "$TAG" --build "$BUILD" --length "$LENGTH" --signature "$SIGNATURE" \
  --notes "$REPO/CHANGELOG.md"
if [ -n "${DRY_RUN:-}" ]; then cat "$FEED/appcast.xml"; echo "==> dry run: not pushed"; exit 0; fi
git -C "$FEED" add appcast.xml
git -C "$FEED" -c user.name="Familiar release" -c user.email="releases@seethroughlab.com" \
  commit -q -m "Familiar Server $VERSION"
git -C "$FEED" push -q origin HEAD:refs/heads/appcast
echo "==> published $VERSION (build $BUILD) to the appcast branch"
