"""Test doubles for the client: a voice, a transcriber, a VAD, audio, a fake Mac, and the client run on them."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import numpy as np
from websockets.asyncio.server import ServerConnection, serve

from app.config import ClientSettings, ListenSettings
from app.services import open_client
from app.stt.listener import ArraySource
from app.stt.vad import SAMPLE_RATE
from mika_shared.events import RuntimeClientEvent, parse_runtime_client_event

HANG = "hang"  # FakeVoice: a sentence with this text never finishes


class FakeVoice:
    """Each sentence becomes 0.05 s of silence per character. "fail" raises; "hang" never returns."""

    sample_rate = 32000

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def load(self) -> None:
        pass

    async def synthesize(self, text: str) -> bytes:
        self.spoken.append(text)
        if text == "fail":
            raise RuntimeError("GenieTTS broke")
        if text == HANG:
            await asyncio.Event().wait()
        return bytes(2 * int(0.05 * len(text) * self.sample_rate))


class FakeTranscriber:
    """Returns the scripted texts in order."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.heard: list[float] = []  # seconds of each utterance

    def load(self) -> None:
        pass

    def transcribe(self, audio: np.ndarray) -> str:
        self.heard.append(len(audio) / SAMPLE_RATE)
        return self.texts.pop(0) if self.texts else ""


def fake_vad(frame: np.ndarray) -> float:
    """Loud frames are speech."""
    return 0.9 if np.abs(frame).max() > 0.05 else 0.0


def speech(seconds: float, amplitude: float = 0.3) -> np.ndarray:
    times = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * 220 * times)).astype(np.float32)


def quiet(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


class FakeMac:
    """A /ws/runtime server on localhost that records what the Acer sends; tests answer through `connection`."""

    def __init__(self) -> None:
        self.received: asyncio.Queue[RuntimeClientEvent] = asyncio.Queue()
        self.connection: ServerConnection | None = None
        self.connected = asyncio.Event()
        self.url = ""

    @asynccontextmanager
    async def running(self) -> AsyncIterator["FakeMac"]:
        async with serve(self._handle, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            self.url = f"ws://127.0.0.1:{port}/ws/runtime"
            yield self

    async def next(self, kind: type | None = None, timeout: float = 5) -> RuntimeClientEvent:
        """The next event the Acer sent (of the given type, skipping others)."""
        async with asyncio.timeout(timeout):
            while True:
                event = await self.received.get()
                if kind is None or isinstance(event, kind):
                    return event

    async def send(self, *events) -> None:
        for event in events:
            await self.connection.send(event.model_dump_json())

    async def _handle(self, connection: ServerConnection) -> None:
        self.connection = connection
        self.connected.set()
        async for data in connection:
            await self.received.put(parse_runtime_client_event(data))


def fast_settings(mac_url: str = "ws://127.0.0.1:9/ws/runtime", **listen) -> ClientSettings:
    """Fast timings; a Mac URL nothing listens on unless a FakeMac's is given."""
    return ClientSettings(
        server_ws_url=mac_url,
        reconnect_max_delay=0.2,
        listen=ListenSettings(echo_guard=0.05, playback_margin=0.5, **listen),
    )


def open_fake_client(voice: FakeVoice, transcriber: FakeTranscriber, audio: np.ndarray | None = None):
    """open_client with the fakes; the microphone hears `audio` in real time, then silence forever."""
    source = ArraySource(audio if audio is not None else quiet(0.1), realtime=True, then_wait=True)

    def factory(settings: ClientSettings):
        return open_client(settings, voice=voice, transcriber=transcriber, source=source, vad=fake_vad)

    return factory
