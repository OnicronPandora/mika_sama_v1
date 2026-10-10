"""FastAPI app: /ws/runtime for the Acer, /health for monitoring. Run it from mika/server with

    python -m app

which also writes server.log (app/__main__.py).
"""

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.ws_runtime import router as ws_runtime_router
from .config import ServerSettings, Settings
from .services import Services, open_services

log = logging.getLogger(__name__)

ServicesFactory = Callable[[Settings], AbstractAsyncContextManager[Services]]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the services at startup; close them at shutdown, after uvicorn has closed the connections."""
    settings = app.state.settings or Settings()
    app.state.settings = settings
    started = time.perf_counter()
    log.info("Starting the Mika-sama server")
    async with app.state.open_services(settings) as services:
        app.state.services = services
        log.info("Ready in %.1f s: waiting for the Acer on /ws/runtime", time.perf_counter() - started)
        try:
            yield
        finally:
            services.state.begin_shutdown()
            log.info("Shutting down")
    log.info("Stopped")


def create_app(settings: Settings | None = None, *, services: ServicesFactory = open_services) -> FastAPI:
    """Settings are read at startup, so importing this module needs no .env file."""
    app = FastAPI(title="Mika-sama server", lifespan=lifespan)
    app.state.settings = settings
    app.state.open_services = services
    app.state.services = None
    server = settings.server if settings else ServerSettings()
    # Spec: CORS middleware. Only for the HTTP API; /ws/runtime checks Origin itself.
    app.add_middleware(CORSMiddleware, allow_origins=list(server.allowed_origins), allow_methods=["GET"])
    app.include_router(ws_runtime_router)

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        services: Services | None = request.app.state.services
        if services is None:
            return JSONResponse({"status": "starting"}, status_code=503)
        state = services.state.state
        body = {
            "status": "ok",
            "database": "not used",
            "services": state.service_status,
            "clients": {component.value: status.value for component, status in state.client_status.items()},
            "shutting_down": state.shutting_down,
        }
        if services.pool is not None:
            try:
                async with services.pool.connection(timeout=2) as conn:
                    await conn.execute("SELECT 1")
            except Exception as e:  # reported rather than raised: this endpoint exists for monitoring
                return JSONResponse({**body, "status": "error", "database": str(e)}, status_code=503)
            body["database"] = "ok"
        return JSONResponse(body)

    return app


app = create_app()
