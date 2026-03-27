#!/bin/bash
set -e

# Fix permissions for mounted volumes (runs as root initially)
chown -R familiar:familiar /app/data /data/art /data/videos 2>/dev/null || true

# Auto-update yt-dlp to pick up latest YouTube fixes
echo "Updating yt-dlp..."
gosu familiar uv pip install -U 'yt-dlp[default]' 2>&1 | tail -3 || echo "WARNING: yt-dlp update failed, using bundled version"

# Initialize database on first run (only for API container, not worker)
if [[ "$1" == "uvicorn"* ]] || [[ "$*" == *"uvicorn"* ]]; then
    echo "Checking database setup..."

    # Ensure pgvector extension exists
    gosu familiar python -c "
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def ensure_extensions():
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
        print('PostgreSQL extensions verified.')

asyncio.run(ensure_extensions())
"

    # Check if alembic_version table exists (indicates Alembic is set up)
    ALEMBIC_SETUP=$(gosu familiar python -c "
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def check_alembic():
    async with engine.begin() as conn:
        result = await conn.execute(text(
            \"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version')\"
        ))
        exists = result.scalar()
        print('yes' if exists else 'no')

asyncio.run(check_alembic())
" 2>/dev/null || echo "no")

    # Check if this is a fresh database or existing without Alembic
    TABLES_EXIST=$(gosu familiar python -c "
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def check_tables():
    async with engine.begin() as conn:
        result = await conn.execute(text(
            \"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'profiles')\"
        ))
        exists = result.scalar()
        print('yes' if exists else 'no')

asyncio.run(check_tables())
" 2>/dev/null || echo "no")

    if [ "$ALEMBIC_SETUP" = "no" ]; then
        if [ "$TABLES_EXIST" = "yes" ]; then
            # Existing database without Alembic - stamp as baseline
            echo "Stamping existing database with Alembic baseline..."
            gosu familiar python -m alembic stamp baseline
        else
            # Fresh database - create from scratch with Alembic
            echo "Initializing fresh database with Alembic..."
            gosu familiar python -m alembic upgrade head
        fi
    else
        # Alembic is set up - run any pending migrations
        echo "Running database migrations..."
        gosu familiar python -m alembic upgrade head
    fi

    # Dispose connection pool to clear any stale schema metadata
    # This ensures the app gets fresh connections after migrations
    gosu familiar python -c "
from app.db.session import engine
import asyncio
asyncio.run(engine.dispose())
print('Connection pool cleared.')
"

    echo "Database ready."
fi

# Drop to familiar user and run the command
exec gosu familiar "$@"
