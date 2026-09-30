import httpx

from app.config import Settings
from app.main import create_app


async def get_health(app) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/health")


async def test_lifespan_opens_and_closes_the_pool(test_db):
    app = create_app(Settings(db=test_db))
    async with app.router.lifespan_context(app):
        pool = app.state.pool
        response = await get_health(app)
        assert (response.status_code, response.json()) == (200, {"status": "ok", "database": "ok"})
        async with pool.connection() as conn:  # every pool connection has the pgvector adapter
            cur = await conn.execute("SELECT '[1,2,3]'::vector")
            (vector,) = await cur.fetchone()
            assert vector.to_list() == [1.0, 2.0, 3.0]
    assert pool.closed


async def test_health_reports_database_problems(test_db):
    app = create_app(Settings(db=test_db))
    async with app.router.lifespan_context(app):
        pass  # the pool is closed after shutdown
    response = await get_health(app)
    assert response.status_code == 503
    assert response.json()["status"] == "error"
