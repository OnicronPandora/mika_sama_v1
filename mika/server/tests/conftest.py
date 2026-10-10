"""Database tests run against TEST_DB_NAME (see .env.example) and are skipped when it isn't set."""

import asyncio
import sys
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection, OperationalError
from psycopg.conninfo import make_conninfo
from pydantic import ValidationError

from app.config import DatabaseSettings
from app.db.schema import apply_schema

if sys.platform == "win32":  # psycopg's async mode can't use Windows' default event loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class SchemaDatabaseSettings(DatabaseSettings):
    """Database settings whose connections use one schema (and public, which holds the vector type)."""

    search_path: str

    def conninfo(self) -> str:
        return make_conninfo(super().conninfo(), options=f"-c search_path={self.search_path},public")


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


async def connect(settings: DatabaseSettings) -> AsyncConnection:
    try:
        return await AsyncConnection.connect(settings.conninfo(), autocommit=True, connect_timeout=5)
    except OperationalError as e:
        pytest.fail(
            f"TEST_DB_NAME is set but the test database is unreachable: {e}\n"
            "On the Acer, start WSL Ubuntu first (wsl -d Ubuntu -e true); see mika/server/README.md."
        )


@pytest.fixture
async def schema(test_db: DatabaseSettings) -> AsyncIterator[str]:
    """A fresh schema in the test database with the tables created. Dropped after the test."""
    name = f"test_{uuid4().hex[:12]}"
    conn = await connect(test_db)
    async with conn:
        await conn.execute(f"CREATE SCHEMA {name}")
        await conn.execute(f"SET search_path TO {name}, public")
        try:
            await apply_schema(conn)
            yield name
        finally:
            await conn.execute(f"DROP SCHEMA {name} CASCADE")


@pytest.fixture
async def db(test_db: DatabaseSettings, schema: str) -> AsyncIterator[AsyncConnection]:
    """An autocommit connection to the fresh schema."""
    conn = await connect(test_db)
    async with conn:
        await conn.execute(f"SET search_path TO {schema}, public")
        await register_vector_async(conn)
        yield conn


@pytest.fixture
def schema_db(test_db: DatabaseSettings, schema: str) -> DatabaseSettings:
    """Settings for code that opens its own connections (the server's pool) to the fresh schema."""
    return SchemaDatabaseSettings(
        name=test_db.name,
        user=test_db.user,
        password=test_db.password,
        host=test_db.host,
        port=test_db.port,
        search_path=schema,
    )
