"""Creates all tables from app.models in the configured database.

Run with: python scripts/create_tables.py
"""
import asyncio

from app.db import init_db
import app.models  # noqa: F401 — registers models on Base.metadata


if __name__ == "__main__":
    asyncio.run(init_db())
    print("tables created")
