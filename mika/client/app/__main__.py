"""Run the client on the Acer, from mika/client:

    python -m app

It connects to the Mac (ClientSettings.server_ws_url) and keeps reconnecting, serves the browser pages on
127.0.0.1:8001, speaks with GenieTTS and listens on the microphone. Logs go to client.log. Ctrl+C stops it.
"""

import uvicorn
from fastapi import FastAPI

from .config import ClientSettings
from .logs import setup_logging
from .main import create_app


def serve(app: FastAPI, settings: ClientSettings) -> None:
    """Run the app with uvicorn until Ctrl+C (tests/serve_fake.py runs the same way)."""
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,  # uvicorn's messages go through setup_logging, into client.log too
        timeout_graceful_shutdown=settings.graceful_shutdown_timeout,
    )


def main() -> None:
    settings = ClientSettings()
    setup_logging(settings.log_file)
    serve(create_app(settings), settings)


if __name__ == "__main__":
    main()
