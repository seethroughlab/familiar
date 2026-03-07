"""
Migration script to add device-based profile tables.
Run this to add profiles, lastfm_profiles, spotify_profiles, and spotify_favorites tables
without dropping existing data.

Usage: uv run python -m app.db.migrate_add_profiles
"""

import asyncio
from typing import cast

from sqlalchemy import Table, text
from sqlalchemy.schema import CreateTable

from app.db.models import LastfmProfile, Profile
from app.db.session import engine


async def migrate() -> None:
    """Add new profile-related tables without dropping existing data."""
    async with engine.begin() as conn:
        # Check which tables already exist
        result = await conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
        )
        existing_tables = {row[0] for row in result.fetchall()}

        # Tables to create
        new_tables = [
            (Profile, "profiles"),
            (LastfmProfile, "lastfm_profiles"),
        ]

        for model, table_name in new_tables:
            if table_name in existing_tables:
                print(f"  Table '{table_name}' already exists, skipping.")
            else:
                # Create the table
                await conn.execute(CreateTable(cast(Table, model.__table__)))
                print(f"  Created table '{table_name}'.")

    print("\nMigration complete!")


if __name__ == "__main__":
    print("Adding device-based profile tables...\n")
    asyncio.run(migrate())
