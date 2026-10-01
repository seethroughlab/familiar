#!/bin/bash
# Build what Familiar Server carries (ADR-0136 point 9), into desktop/macos/build/payload/.
#
#   postgres/   PostgreSQL + pgvector, from source, depending on nothing outside the system
#   python/     python-build-standalone CPython 3.11 with the backend's locked `analysis` deps
#   backend/    the backend (app/, migrations/, alembic.ini) and the built web admin in static/
#
#   bin/, lib/  ffmpeg + ffprobe, LGPL, shared libraries, with LAME for mixtape MP3s
#   lib/        libchromaprint, for AcoustID fingerprints, loaded by path (FAMILIAR_CHROMAPRINT_LIBRARY)
#
# Needs Xcode's command-line tools, curl and cmake (for Chromaprint).
#
# Python is pinned to 3.11: on 3.12, basic-pitch resolves to tensorflow-macos, which has no 3.12
# wheels (ADR-0136 point 9).
#
# usage: scripts/build-payload.sh [tag]      (defaults to "dev")
#
# The version is the release tag, `v` and all, exactly as the Docker image is given it: the backend
# reports it, and downloads its CLAP encoders from the release of that name (ADR-0132 point 8).
set -euo pipefail
# Native arm64 only. Under Rosetta — the x86_64 GitHub runner on an Apple Silicon Mac — every
# child would build for Intel: ffmpeg probes for x86 assembly and the Swift binaries come out
# x86_64 beside an arm64 Python. So re-run natively, and refuse a real Intel Mac outright.
if [ "$(uname -m)" != arm64 ]; then
  if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" = 1 ]; then exec arch -arm64 /bin/bash "$0" "$@"; fi
  echo "Familiar Server is built on Apple Silicon; this machine is $(uname -m)" >&2; exit 1
fi

PG_VERSION=16.15
FFMPEG_VERSION=8.1.3
LAME_VERSION=3.100
CHROMAPRINT_VERSION=1.6.1
PGVECTOR_VERSION=0.8.6
PBS_RELEASE=20260929
PBS_PYTHON=3.11.16

HERE=$(cd "$(dirname "$0")/.." && pwd)            # desktop/macos
REPO=$(cd "$HERE/../.." && pwd)
OUT=$HERE/build/payload
SRC=$HERE/build/src
VERSION=${1:-dev}
case "$VERSION" in
  dev|v[0-9]*) ;;
  *) echo "version '$VERSION' is not a release tag (v…) or dev; the server would fetch its CLAP" \
       "encoders from a release that does not exist" >&2; exit 1 ;;
esac
JOBS=$(sysctl -n hw.ncpu)

mkdir -p "$OUT" "$SRC"

# --- PostgreSQL + pgvector ------------------------------------------------------------------
if [ ! -x "$OUT/postgres/bin/postgres" ]; then
  echo "==> PostgreSQL $PG_VERSION"
  (cd "$SRC" && curl -sfL "https://ftp.postgresql.org/pub/source/v$PG_VERSION/postgresql-$PG_VERSION.tar.bz2" | tar xj)
  (cd "$SRC/postgresql-$PG_VERSION" \
    && ./configure --prefix="$OUT/postgres" --without-icu --without-readline --without-zlib \
         --without-openssl --without-llvm --disable-rpath >/dev/null \
    && make -s -j"$JOBS" >/dev/null && make -s install >/dev/null \
    && make -s -C contrib/pg_trgm install >/dev/null)   # the search indexes' trigrams (the baseline migration)
  # Relocatable: the binaries that link libpq find it beside themselves, not at the build prefix.
  install_name_tool -id @rpath/libpq.5.dylib "$OUT/postgres/lib/libpq.5.dylib" 2>/dev/null
  for b in "$OUT"/postgres/bin/*; do
    if otool -L "$b" 2>/dev/null | grep -q "$OUT/postgres/lib/libpq.5.dylib"; then
      install_name_tool -change "$OUT/postgres/lib/libpq.5.dylib" @executable_path/../lib/libpq.5.dylib "$b" 2>/dev/null
    fi
  done
  echo "==> pgvector $PGVECTOR_VERSION"
  (cd "$SRC" && curl -sfL "https://github.com/pgvector/pgvector/archive/refs/tags/v$PGVECTOR_VERSION.tar.gz" | tar xz)
  (cd "$SRC/pgvector-$PGVECTOR_VERSION" \
    && make -s PG_CONFIG="$OUT/postgres/bin/pg_config" >/dev/null \
    && make -s install PG_CONFIG="$OUT/postgres/bin/pg_config" >/dev/null)
  # What the server never uses, and should not ship.
  rm -rf "$OUT/postgres/include" "$OUT/postgres/lib/pgxs"
fi

# --- ffmpeg (LGPL) ------------------------------------------------------------------------------
# What the backend asks of it: decode any library's audio and embedded cover art, remux FLAC,
# encode AAC (phone downloads, ADR-0118) and MP3 (mixtapes, via LAME), write JPEG covers, and
# ffprobe. All of it is LGPL: no --enable-gpl, no nonfree, and LAME is LGPL too. Shared libraries
# rather than a static binary, which is what lets the LGPL's relinking terms be met: the dylibs in
# lib/ can be replaced. --disable-autodetect so nothing from Homebrew is linked by accident; zlib
# (for PNG covers) and the audio frameworks are macOS's own.
if [ ! -x "$OUT/bin/ffmpeg" ]; then
  echo "==> LAME $LAME_VERSION"
  (cd "$SRC" && curl -sfL "https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz" | tar xz)
  # LAME 3.100's export list names `lame_init_old`, which no longer exists, and Apple's linker
  # refuses it. The same one-line fix Homebrew applies.
  sed -i '' '/lame_init_old/d' "$SRC/lame-$LAME_VERSION/include/libmp3lame.sym"
  (cd "$SRC/lame-$LAME_VERSION" \
    && ./configure --prefix="$SRC/lame-install" --enable-shared --disable-static --disable-frontend >/dev/null \
    && make -s -j"$JOBS" >/dev/null && make -s install >/dev/null)
  echo "==> ffmpeg $FFMPEG_VERSION"
  (cd "$SRC" && curl -sfL "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" | tar xJ)
  (cd "$SRC/ffmpeg-$FFMPEG_VERSION" \
    && ./configure --prefix="$SRC/ffmpeg-install" \
         --enable-shared --disable-static --disable-autodetect \
         --disable-doc --disable-ffplay --disable-network --disable-debug \
         --enable-zlib --enable-audiotoolbox \
         --enable-libmp3lame \
         --extra-cflags="-I$SRC/lame-install/include" --extra-ldflags="-L$SRC/lame-install/lib" \
         --install-name-dir='@rpath' \
         --extra-ldexeflags='-Wl,-rpath,@executable_path/../lib' >/dev/null \
    && make -s -j"$JOBS" >/dev/null && make -s install >/dev/null)
  mkdir -p "$OUT/bin" "$OUT/lib"
  cp "$SRC/ffmpeg-install/bin/ffmpeg" "$SRC/ffmpeg-install/bin/ffprobe" "$OUT/bin/"
  cp -P "$SRC"/ffmpeg-install/lib/*.dylib "$OUT/lib/"
  cp -P "$SRC"/lame-install/lib/libmp3lame*.dylib "$OUT/lib/"
  # LAME records its build path as its install name; point libavcodec at it by @rpath instead.
  LAME_DYLIB=$(basename "$(readlink "$OUT/lib/libmp3lame.dylib" || echo libmp3lame.0.dylib)")
  install_name_tool -id "@rpath/$LAME_DYLIB" "$OUT/lib/$LAME_DYLIB" 2>/dev/null
  for f in "$OUT"/bin/ffmpeg "$OUT"/bin/ffprobe "$OUT"/lib/*.dylib; do
    [ -L "$f" ] && continue
    install_name_tool -change "$SRC/lame-install/lib/$LAME_DYLIB" "@rpath/$LAME_DYLIB" "$f" 2>/dev/null
  done
  # Nothing may point outside the bundle: a path under build/ exists only on this machine.
  if otool -L "$OUT"/bin/ffmpeg "$OUT"/bin/ffprobe "$OUT"/lib/*.dylib | grep -q "$SRC"; then
    echo "ffmpeg still links something under $SRC" >&2; exit 1
  fi
  # Written beside the binaries, for the LGPL's notice and so what shipped can be rebuilt.
  cat > "$OUT/lib/FFMPEG-SOURCE.txt" <<NOTE
ffmpeg $FFMPEG_VERSION (LGPL-2.1-or-later), https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz
LAME $LAME_VERSION (LGPL-2.0-or-later), https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz
Built by desktop/macos/scripts/build-payload.sh in https://github.com/seethroughlab/familiar
as shared libraries in this directory; they may be replaced with compatible builds.
NOTE
fi

# --- Chromaprint (LGPL) -------------------------------------------------------------------------
# The library, not `fpcalc`: the Docker image fingerprints through pyacoustid's library path, and the
# community cache keys on the result, so the Mac must take the same path (measured in
# `analysis._FINGERPRINT_CHILD`, which also decodes with the ffmpeg above, as the image does).
# kissfft is the image's FFT; vDSP measured identical, and this keeps the two builds alike.
if [ ! -f "$OUT/lib/libchromaprint.1.dylib" ]; then
  echo "==> Chromaprint $CHROMAPRINT_VERSION"
  (cd "$SRC" && curl -sfL "https://github.com/acoustid/chromaprint/releases/download/v$CHROMAPRINT_VERSION/chromaprint-$CHROMAPRINT_VERSION.tar.gz" | tar xz)
  cmake -S "$SRC/chromaprint-$CHROMAPRINT_VERSION" -B "$SRC/chromaprint-build" -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON -DBUILD_TOOLS=OFF -DBUILD_TESTS=OFF -DFFT_LIB=kissfft \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0 >/dev/null
  cmake --build "$SRC/chromaprint-build" -j"$JOBS" >"$SRC/chromaprint-build.log" 2>&1 \
    || { tail -30 "$SRC/chromaprint-build.log"; exit 1; }
  mkdir -p "$OUT/lib"
  cp "$SRC/chromaprint-build/src/libchromaprint.$CHROMAPRINT_VERSION.dylib" "$OUT/lib/libchromaprint.1.dylib"
  install_name_tool -id @rpath/libchromaprint.1.dylib "$OUT/lib/libchromaprint.1.dylib" 2>/dev/null
  if otool -L "$OUT/lib/libchromaprint.1.dylib" | tail -n +2 | grep -v -e '@rpath/' -e '^\s*/usr/lib/' -e '^\s*/System/' | grep -q .; then
    echo "libchromaprint links something outside the system" >&2; exit 1
  fi
  cat > "$OUT/lib/CHROMAPRINT-SOURCE.txt" <<NOTE
Chromaprint $CHROMAPRINT_VERSION (LGPL-2.1-or-later), https://github.com/acoustid/chromaprint/releases/download/v$CHROMAPRINT_VERSION/chromaprint-$CHROMAPRINT_VERSION.tar.gz
Built by desktop/macos/scripts/build-payload.sh in https://github.com/seethroughlab/familiar
as a shared library in this directory; it may be replaced with a compatible build.
NOTE
fi

# --- Python + the backend's dependencies ------------------------------------------------------
if [ ! -x "$OUT/python/bin/python3" ]; then
  echo "==> CPython $PBS_PYTHON ($PBS_RELEASE)"
  (cd "$OUT" && curl -sfL "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_RELEASE/cpython-$PBS_PYTHON%2B$PBS_RELEASE-aarch64-apple-darwin-install_only.tar.gz" | tar xz)
fi
echo "==> backend dependencies (analysis extra, from uv.lock)"
(cd "$REPO/backend" && uv export --frozen --no-dev --extra analysis --no-hashes --no-emit-project -q > "$SRC/requirements.txt")
uv pip install -q --python "$OUT/python/bin/python3" --break-system-packages -r "$SRC/requirements.txt"

# --- The backend and the web admin -------------------------------------------------------------
echo "==> backend $VERSION"
rm -rf "$OUT/backend" && mkdir -p "$OUT/backend"
cp -R "$REPO/backend/app" "$REPO/backend/migrations" "$REPO/backend/alembic.ini" "$OUT/backend/"
find "$OUT/backend" -name "__pycache__" -type d -prune -exec rm -rf {} +
echo "$VERSION" > "$OUT/backend/VERSION"   # get_app_version reads it (ADR-0132 point 3)
echo "==> web admin"
(cd "$REPO" && pnpm -s --filter @familiar/web build >/dev/null)
cp -R "$REPO/packages/web/dist" "$OUT/backend/static"

du -sh "$OUT"/* | sed "s#$OUT/##"
