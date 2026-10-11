"""FastAPI app: /ws/chat for the browser pages, /health for checks. Run it from mika/client with

    python -m app

which also writes client.log (app/__main__.py).
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.ws_chat import Page
from .api.ws_chat import router as ws_chat_router
from .config import ClientSettings
from .services import ClientServices, open_client

log = logging.getLogger(__name__)

ServicesFactory = Callable[[ClientSettings], AbstractAsyncContextManager[ClientServices]]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings or ClientSettings()
    app.state.settings = settings
    log.info("Starting the Mika-sama client; the Mac is at %s", settings.server_ws_url)
    async with app.state.open_services(settings) as services:
        app.state.services = services
        log.info("Ready: pages connect to ws://%s:%s/ws/chat?page=avatar or ?page=admin", settings.host, settings.port)
        yield
        log.info("Shutting down")
    log.info("Stopped")


def create_app(settings: ClientSettings | None = None, *, services: ServicesFactory = open_client) -> FastAPI:
    app = FastAPI(title="Mika-sama client", lifespan=lifespan)
    app.state.settings = settings
    app.state.open_services = services
    app.state.services = None
    allowed = (settings or ClientSettings()).allowed_origins
    app.add_middleware(CORSMiddleware, allow_origins=list(allowed), allow_methods=["GET"])  # spec: CORS
    app.include_router(ws_chat_router)

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        services: ClientServices | None = request.app.state.services
        if services is None:
            return JSONResponse({"status": "starting"}, status_code=503)
        return JSONResponse(
            {
                "status": "ok",
                "mac": "connected" if services.connector.connected else "not connected",
                "parts": {component.value: state.value for component, state in services.relay.statuses.items()},
                "pages": {page.value: services.pages.count(page) for page in Page},
                "microphone": "muted" if services.gate.muted else "open",
            }
        )

    return app


app = create_app()
