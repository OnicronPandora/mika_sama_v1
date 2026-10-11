"""Ctrl+C while Mika's voice is in the middle of a sentence stops the client within seconds (the old client's
STT system deadlocked: docs/top_secret.md, known issues)."""

import asyncio
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from fakes import HANG, FakeMac
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from mika_shared.enums import Emotion, FilterAction
from mika_shared.events import EmotionUpdate, Sentence, TurnStart, parse_chat_server_event

CLIENT_DIR = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def connect_when_up(url: str, process: subprocess.Popen, output: Path):
    async with asyncio.timeout(30):
        while True:
            assert process.poll() is None, "the client exited:\n" + output.read_text(encoding="utf-8", errors="replace")
            try:
                return await connect(url)
            except OSError:
                await asyncio.sleep(0.2)


async def test_ctrl_c_mid_sentence_stops_the_client_within_seconds(tmp_path):
    port, log_file, output = free_port(), tmp_path / "client.log", tmp_path / "output.txt"
    async with FakeMac().running() as mac:
        with output.open("wb") as out:
            process = subprocess.Popen(
                [sys.executable, str(CLIENT_DIR / "tests" / "serve_fake.py"), str(port), str(log_file), mac.url],
                cwd=CLIENT_DIR,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
        try:
            avatar = await connect_when_up(f"ws://127.0.0.1:{port}/ws/chat?page=avatar", process, output)
            async with avatar:
                async with asyncio.timeout(10):
                    await mac.connected.wait()
                await mac.send(
                    TurnStart(turn_id="t1", emotion=Emotion.HAPPY),
                    Sentence(turn_id="t1", seq=0, text=HANG, action=FilterAction.ALLOW),  # never finishes
                )
                async with asyncio.timeout(5):
                    assert isinstance(parse_chat_server_event(await avatar.recv()), EmotionUpdate)
                await asyncio.sleep(0.2)  # the voice is now stuck on the sentence
                process.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT)
                interrupted = time.perf_counter()
                try:
                    async with asyncio.timeout(5):
                        await avatar.recv()
                except ConnectionClosed:
                    pass
            await asyncio.to_thread(process.wait, 10)
            elapsed = time.perf_counter() - interrupted
        finally:
            if process.poll() is None:
                process.kill()
    log = log_file.read_text(encoding="utf-8")
    assert elapsed < 3, log
    assert "Stopped" in log, log
    assert "graceful shutdown exceeded" not in log, log
