"""FastAPI entry point. Run from mika/server:

    uvicorn app.main:app --port 8000

Phase 2 wires the database; the /ws/runtime endpoint and the turn pipeline come in Phase 6.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .db.pool import open_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database pool at startup and close it at shutdown."""
    settings = app.state.settings or Settings()
    app.state.settings = settings
    app.state.pool = await open_pool(settings.db)
    try:
        yield
    finally:
        await app.state.pool.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Settings are read at startup, so importing this module needs no .env file."""
    app = FastAPI(title="Mika-sama server", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        try:
            async with request.app.state.pool.connection(timeout=2) as conn:
                await conn.execute("SELECT 1")
        except Exception as e:  # reported rather than raised: this endpoint exists for monitoring
            return JSONResponse({"status": "error", "database": str(e)}, status_code=503)
        return JSONResponse({"status": "ok", "database": "ok"})

    return app


app = create_app()
