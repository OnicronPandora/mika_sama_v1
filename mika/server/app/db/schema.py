"""Apply scripts/setup_db.sql.

    python -m app.db.schema    # from mika/server; uses the database in mika/server/.env
"""

import asyncio
import sys

from psycopg import AsyncConnection

from ..config import SERVER_DIR, DatabaseSettings

SCHEMA_FILE = SERVER_DIR / "scripts" / "setup_db.sql"


async def apply_schema(conn: AsyncConnection) -> None:
    """Create any missing tables and indexes. Safe to run on an existing database."""
    await conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))


async def main() -> None:
    db = DatabaseSettings()
    async with await AsyncConnection.connect(db.conninfo(), autocommit=True) as conn:
        await apply_schema(conn)
    print(f"Schema applied to database {db.name!r} on {db.host}:{db.port}")


if __name__ == "__main__":
    if sys.platform == "win32":  # psycopg's async mode can't use Windows' default event loop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
