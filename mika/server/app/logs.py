"""Logging (spec: "Store in server.log file"): the server's and uvicorn's messages go to server.log and the
console. python -m app sets it up before uvicorn starts, so the startup lines are in the file too."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    """Safe to call more than once."""
    root = logging.getLogger()
    if any(getattr(handler, "mika", False) for handler in root.handlers):
        return
    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    for handler in (file_handler, logging.StreamHandler()):
        handler.setFormatter(logging.Formatter(FORMAT))
        handler.mika = True
        root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # it would log every request to Ollama
