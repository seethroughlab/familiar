"""
Database initialization script for development.
Drops and recreates all tables - use only during active development.
"""

import asyncio

from sqlalchemy import text

from app.db.models import Base
from app.db.session import engine


async def init_db() -> None:
    """Drop all tables and recreate them."""
    async with engine.begin() as conn:
        # Ensure required extensions are enabled
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

        # Drop all tables
        await conn.run_sync(Base.metadata.drop_all)

        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

    print("Database initialized successfully.")


async def check_db() -> None:
    """Check database connection and list tables."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            )
        )
        tables = [row[0] for row in result.fetchall()]

    if tables:
        print(f"Found {len(tables)} tables:")
        for table in tables:
            print(f"  - {table}")
    else:
        print("No tables found. Run 'make reset-db' to initialize.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "check":
        asyncio.run(check_db())
    else:
        asyncio.run(init_db())
