"""The server's connection pool. The FastAPI lifespan opens it at startup and closes it at shutdown.

Each ``async with pool.connection() as conn:`` block is one transaction: it commits when the block
ends normally and rolls back on an exception.
"""

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from ..config import DatabaseSettings


async def _configure(conn: AsyncConnection) -> None:
    await register_vector_async(conn)
    await conn.commit()  # registering runs a query; the pool needs the connection back idle


async def open_pool(db: DatabaseSettings, *, min_size: int = 1, max_size: int = 4, timeout: float = 10) -> AsyncConnectionPool:
    """Open the pool and wait for a working connection. Raises PoolTimeout if the database is unreachable."""
    pool = AsyncConnectionPool(
        db.conninfo(),
        min_size=min_size,
        max_size=max_size,
        open=False,
        configure=_configure,
        check=AsyncConnectionPool.check_connection,
        name="mika",
    )
    try:
        await pool.open(wait=True, timeout=timeout)
    except BaseException:
        await pool.close()
        raise
    return pool
