"""The app's startup and shutdown with the real database and a fake LLM and embedder."""

import logging
from functools import partial

import httpx
import pytest
from fakes import FakeEmbedder, FakeEngine

from app.config import Settings
from app.main import create_app
from app.services import open_services


def make_app(db_settings, engine=None):
    settings = Settings(db=db_settings)
    engine = engine or FakeEngine()
    return create_app(settings, services=partial(open_services, engine=engine, embedder=FakeEmbedder()))


async def get_health(app) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/health")


async def test_startup_loads_everything_and_shutdown_closes_the_pool(schema_db, db):
    await db.execute("INSERT INTO personality_traits (trait) VALUES ('Loves rainy days')")
    app = make_app(schema_db)
    async with app.router.lifespan_context(app):
        services = app.state.services
        response = await get_health(app)
        assert response.status_code == 200
        body = response.json()
        assert (body["status"], body["database"]) == ("ok", "ok")
        assert body["services"] == {"database": "ok", "embeddings": "ok", "ollama": "ok"}
        assert "- Loves rainy days" in services.runner.system_prompt  # learned traits are read at startup
        # Ollama was warmed up with the start of Pandora's next prompt (no history yet: the system prompt).
        assert services.engine.warm_ups == [[{"role": "system", "content": services.runner.system_prompt}]]
        async with services.pool.connection() as conn:  # every pool connection has the pgvector adapter
            cur = await conn.execute("SELECT '[1,2,3]'::vector")
            (vector,) = await cur.fetchone()
            assert vector.to_list() == [1.0, 2.0, 3.0]
    assert services.pool.closed


async def test_health_reports_database_problems(schema_db):
    app = make_app(schema_db)
    async with app.router.lifespan_context(app):
        pass  # the pool is closed after shutdown
    response = await get_health(app)
    assert response.status_code == 503
    assert response.json()["status"] == "error"


async def test_health_before_startup():
    response = await get_health(create_app())
    assert (response.status_code, response.json()) == (503, {"status": "starting"})


class OllamaDown(FakeEngine):
    async def warm_up(self, messages, *, label="warm-up") -> None:
        raise ConnectionError("Failed to connect to Ollama")


async def test_startup_fails_clearly_when_ollama_is_down(schema_db, caplog):
    app = make_app(schema_db, engine=OllamaDown())
    with caplog.at_level(logging.ERROR), pytest.raises(ConnectionError):
        async with app.router.lifespan_context(app):
            pass
    assert "Ollama isn't reachable" in caplog.text
