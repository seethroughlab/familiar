#!/bin/bash
set -e

chown -R familiar:familiar /data/music /data/art /data/videos /app/data 2>/dev/null || true

# The API container: started by `python -m app.serve` (ADR-0141 point 5), or by uvicorn in an image
# or override that predates it.
if [[ "$*" == *"app.serve"* ]] || [[ "$1" == "uvicorn"* ]] || [[ "$*" == *"uvicorn"* ]]; then
    echo "Ensuring pgvector extension..."
    gosu familiar python -c "
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def ensure_ext():
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
asyncio.run(ensure_ext())
print('pgvector ready')
"

    echo "Running alembic migrations..."
    gosu familiar python -m alembic upgrade head

    # **Link the seeded tracks to canonical artists and albums (ADR-0052).** A real server does
    # this as a sync scans each file. The demo never syncs: its library arrives as rows from
    # `demo-seed.sql.gz`, whose tracks carry `canonical_artist_id = NULL`, so for two months the
    # demo had no artists at all — an empty Artists list, and every artist page a 404 ("That artist
    # isn't on this server any more") in front of App Store reviewers. Both backfills are idempotent
    # and local (`--no-mb`: no MusicBrainz), seconds on 32 tracks. A failure is logged, not fatal:
    # a demo without artist pages beats a demo that does not boot.
    echo "Linking tracks to artists and albums..."
    gosu familiar python -m app.cli.backfill_artists --no-mb --log-level WARNING \
        || echo "WARNING: artist backfill failed; artist pages will 404"
    gosu familiar python -m app.cli.backfill_albums --log-level WARNING \
        || echo "WARNING: album backfill failed"

    gosu familiar python -c "
from app.db.session import engine
import asyncio
asyncio.run(engine.dispose())
"
    echo "Database ready."
fi

exec gosu familiar "$@"
