#!/bin/bash
# ADR-0136 point 8's spike: is Familiar Server's payload viable inside the App Sandbox?
# Results are recorded in docs/decisions/ADR-0136-familiar-server-runs-in-the-background.md.
#
# usage: build-spike.sh <spike dir> <variant: strict|dlv>
#
# <spike dir> must hold:
#   app-src/main.swift       (this directory's main.swift)
#   payload/experiments.py   (this directory's experiments.py)
#   payload/postgres         PostgreSQL 16 built from source with no external deps:
#       ./configure --prefix=<spike>/payload/postgres --without-icu --without-readline \
#           --without-zlib --without-openssl --without-llvm --disable-rpath && make && make install
#       then pgvector: make PG_CONFIG=<spike>/payload/postgres/bin/pg_config && make install
#       then point initdb/psql/pg_isready at @executable_path/../lib/libpq.5.dylib (install_name_tool)
#   payload/python           python-build-standalone cpython-3.11 aarch64-apple-darwin install_only,
#       with `python -m pip install numpy==1.26.4 onnxruntime==1.24.1`
#   music-ro/                a folder with one file, granted read-only
#
# Run:  open -W -n --env SPIKE_SEMPREFIX=7JL9RZ9C8P.fs/mp <spike>/FamiliarSpike.app --args <spike>/music-ro
# The report lands in ~/Library/Containers/com.seethroughlab.familiar-spike/Data/report.json.
# Omit --env to see the semaphore failure the app group fixes.
set -euo pipefail
SP=$1; VARIANT=${2:-strict}
APP=$SP/FamiliarSpike.app
ID=$(security find-identity -v -p codesigning | grep "Apple Development" | grep -v REVOKED | head -1 | awk '{print $2}')
rm -rf $APP && mkdir -p $APP/Contents/MacOS $APP/Contents/Resources
swiftc -O -o $APP/Contents/MacOS/FamiliarSpike $SP/app-src/main.swift
cp -R $SP/payload/postgres $SP/payload/python $SP/payload/experiments.py $APP/Contents/Resources/
cat > $APP/Contents/Info.plist <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.seethroughlab.familiar-spike</string>
<key>CFBundleExecutable</key><string>FamiliarSpike</string>
<key>CFBundleName</key><string>FamiliarSpike</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSUIElement</key><true/>
</dict></plist>
PL
cat > $SP/child.entitlements <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>com.apple.security.app-sandbox</key><true/>
<key>com.apple.security.inherit</key><true/>
$( [ "$VARIANT" = dlv ] && echo '<key>com.apple.security.cs.disable-library-validation</key><true/>' )
</dict></plist>
PL
cat > $SP/parent.entitlements <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>com.apple.security.app-sandbox</key><true/>
<key>com.apple.security.network.server</key><true/>
<key>com.apple.security.network.client</key><true/>
<key>com.apple.security.application-groups</key><array><string>7JL9RZ9C8P.fs</string></array>
<key>com.apple.security.temporary-exception.files.absolute-path.read-only</key>
<array><string>$SP/music-ro/</string></array>
</dict></plist>
PL
# Libraries first (no entitlements), then executables (sandbox + inherit), then the app.
find $APP/Contents/Resources -type f \( -name "*.dylib" -o -name "*.so" \) -print0 | xargs -0 -n 50 codesign -f -s "$ID" -o runtime --timestamp=none 2>/dev/null
find $APP/Contents/Resources -type f -perm +111 ! -name "*.dylib" ! -name "*.so" -print0 | while IFS= read -r -d '' f; do
  if file -b "$f" | grep -q "Mach-O"; then codesign -f -s "$ID" -o runtime --timestamp=none --entitlements $SP/child.entitlements "$f" 2>/dev/null; fi
done
codesign -f -s "$ID" -o runtime --timestamp=none --entitlements $SP/parent.entitlements $APP
codesign --verify --strict $APP && echo "signed ($VARIANT) with $ID"
du -sh $APP
