"""Ctrl+C in the middle of a turn stops the server within seconds (plan, Phase 6 "done when").

Regression test for the old server's known issues (docs/top_secret.md): a deadlocked work queue, and a
WebSocket disconnect that swallowed CancelledError, so the server couldn't shut down.
"""

import asyncio
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from mika_shared.enums import MessageSource
from mika_shared.events import TurnStart, UserMessage, parse_runtime_server_event

SERVER_DIR = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def interrupt(process: subprocess.Popen) -> None:
    """Ctrl+C. On Windows a child process can only be sent Ctrl+Break, which uvicorn handles the same way."""
    process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT)


async def connect_when_up(url: str, process: subprocess.Popen, output: Path):
    async with asyncio.timeout(30):
        while True:
            assert process.poll() is None, "the server exited:\n" + output.read_text(encoding="utf-8", errors="replace")
            try:
                return await connect(url)
            except OSError:
                await asyncio.sleep(0.2)


async def test_ctrl_c_during_a_turn_stops_the_server_within_seconds(tmp_path):
    port, log_file, output = free_port(), tmp_path / "server.log", tmp_path / "output.txt"
    with output.open("wb") as out:
        process = subprocess.Popen(
            [sys.executable, str(SERVER_DIR / "tests" / "serve_fake.py"), str(port), str(log_file)],
            cwd=SERVER_DIR,
            stdout=out,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
    try:
        acer = await connect_when_up(f"ws://127.0.0.1:{port}/ws/runtime", process, output)
        async with acer:
            await acer.send(UserMessage(user_id="admin", message="Hi!", source=MessageSource.CHAT).model_dump_json())
            async with asyncio.timeout(5):
                assert isinstance(parse_runtime_server_event(await acer.recv()), TurnStart)
            # The turn is now waiting on the LLM, which never answers.
            interrupt(process)
            interrupted = time.perf_counter()
            try:
                async with asyncio.timeout(5):
                    await acer.recv()
            except ConnectionClosed:
                pass  # the server closed the connection as it shut down
        await asyncio.to_thread(process.wait, 10)
        elapsed = time.perf_counter() - interrupted
    finally:
        if process.poll() is None:
            process.kill()
    log = log_file.read_text(encoding="utf-8")
    assert elapsed < 3, log
    assert "Stopped" in log, log  # the lifespan finished: the services were closed
    assert "graceful shutdown exceeded" not in log, log  # the turn stopped by itself; uvicorn didn't have to
