#!/bin/bash
set -e

chown -R familiar:familiar /data/music /data/art /data/videos /app/data 2>/dev/null || true

if [[ "$1" == "uvicorn"* ]] || [[ "$*" == *"uvicorn"* ]]; then
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

    gosu familiar python -c "
from app.db.session import engine
import asyncio
asyncio.run(engine.dispose())
"
    echo "Database ready."
fi

exec gosu familiar "$@"
