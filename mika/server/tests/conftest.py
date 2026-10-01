"""Database tests run against TEST_DB_NAME (see .env.example) and are skipped when it isn't set."""

import asyncio
import sys
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection, OperationalError
from pydantic import ValidationError

from app.config import DatabaseSettings
from app.db.schema import apply_schema

if sys.platform == "win32":  # psycopg's async mode can't use Windows' default event loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def test_db() -> DatabaseSettings:
    """Settings pointing at the test database, which the tests are allowed to wipe."""
    try:
        settings = DatabaseSettings()
    except ValidationError:
        pytest.skip("no database settings in the environment or mika/server/.env")
    if not settings.test_name:
        pytest.skip("TEST_DB_NAME is not set")
    return settings.model_copy(update={"name": settings.test_name})


@pytest.fixture
async def db(test_db: DatabaseSettings) -> AsyncIterator[AsyncConnection]:
    """An autocommit connection to a fresh schema in the test database, with the tables created."""
    try:
        conn = await AsyncConnection.connect(test_db.conninfo(), autocommit=True, connect_timeout=5)
    except OperationalError as e:
        pytest.fail(
            f"TEST_DB_NAME is set but the test database is unreachable: {e}\n"
            "On the Acer, start WSL Ubuntu first (wsl -d Ubuntu -e true); see mika/server/README.md."
        )
    schema = f"test_{uuid4().hex[:12]}"
    async with conn:
        await conn.execute(f"CREATE SCHEMA {schema}")
        await conn.execute(f"SET search_path TO {schema}, public")  # public holds the vector type
        try:
            await apply_schema(conn)
            await register_vector_async(conn)
            yield conn
        finally:
            await conn.execute(f"DROP SCHEMA {schema} CASCADE")
