"""Run the server, from mika/server (Ollama and PostgreSQL first):

    python -m app

It listens on ServerSettings.host/port (0.0.0.0:8000, for the Acer) and logs to server.log. Ctrl+C stops it,
even in the middle of a turn.
"""

import sys

import uvicorn
from fastapi import FastAPI

from .config import Settings
from .logs import setup_logging
from .main import create_app


def serve(app: FastAPI, settings: Settings) -> None:
    """Run the app with uvicorn until Ctrl+C (tests/serve_fake.py runs the same way)."""
    uvicorn.run(
        app,
        host=settings.server.host,
        port=settings.server.port,
        log_config=None,  # uvicorn's messages go through setup_logging, into server.log too
        timeout_graceful_shutdown=settings.server.graceful_shutdown_timeout,
        # psycopg's async mode needs a selector event loop; on Windows uvicorn would pick the Proactor loop.
        loop="asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto",
    )


def main() -> None:
    settings = Settings()
    setup_logging(settings.server.log_file)
    serve(create_app(settings), settings)


if __name__ == "__main__":
    main()
