#!/bin/bash
# Build what Familiar Server carries (ADR-0136 point 9), into desktop/macos/build/payload/.
#
#   postgres/   PostgreSQL + pgvector, from source, depending on nothing outside the system
#   python/     python-build-standalone CPython 3.11 with the backend's locked `analysis` deps
#   backend/    the backend (app/, migrations/, alembic.ini) and the built web admin in static/
#
# Python is pinned to 3.11: on 3.12, basic-pitch resolves to tensorflow-macos, which has no 3.12
# wheels (ADR-0136 point 9). Not yet here: ffmpeg (artwork extraction and transcodes need it).
#
# usage: scripts/build-payload.sh [version]      (version defaults to "dev")
set -euo pipefail

PG_VERSION=16.15
PGVECTOR_VERSION=0.8.6
PBS_RELEASE=20260929
PBS_PYTHON=3.11.16

HERE=$(cd "$(dirname "$0")/.." && pwd)            # desktop/macos
REPO=$(cd "$HERE/../.." && pwd)
OUT=$HERE/build/payload
SRC=$HERE/build/src
VERSION=${1:-dev}
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

mkdir -p "$OUT/bin"   # where ffmpeg will go; on the server's PATH first
du -sh "$OUT"/* | sed "s#$OUT/##"
