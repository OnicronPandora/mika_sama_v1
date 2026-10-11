"""Listening to Pandora: microphone frames -> voice activity -> utterances -> Whisper -> the Mac.

While the half-duplex gate is muted (Mika is answering), frames are dropped, and detection starts over when it
unmutes. Whisper takes a second or two on the Acer's CPU; frames that queue up meanwhile are processed after.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

import numpy as np

from ..config import ListenSettings
from .engine import Transcriber
from .gate import HalfDuplexGate
from .vad import FRAME, SAMPLE_RATE, Segmenter, SileroVad, rms

log = logging.getLogger(__name__)


class AudioSource(Protocol):
    def frames(self) -> AsyncIterator[np.ndarray]:
        """FRAME-sample float32 frames at SAMPLE_RATE, mono."""
        ...


class Microphone:
    """The default (or configured) microphone, through sounddevice."""

    def __init__(self, device: int | str | None = None, *, max_queued: int = 300) -> None:
        self._device = device
        self._max_queued = max_queued  # about 10 s of frames; the oldest are dropped beyond that

    async def frames(self) -> AsyncIterator[np.ndarray]:
        import sounddevice

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=self._max_queued)

        def put(frame: np.ndarray) -> None:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(frame)

        def callback(indata, frames, time_info, status) -> None:  # runs in PortAudio's thread
            loop.call_soon_threadsafe(put, indata[:, 0].copy())

        stream = sounddevice.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=FRAME, device=self._device, callback=callback
        )
        stream.start()
        log.info("Listening on %s", sounddevice.query_devices(stream.device)["name"])
        try:
            while True:
                yield await queue.get()
        finally:
            stream.stop()
            stream.close()


class ArraySource:
    """Audio from an array, for tests and python -m app.stt.check --file. realtime: pace it like a microphone."""

    def __init__(self, audio: np.ndarray, *, realtime: bool = False, then_wait: bool = False) -> None:
        self._audio = audio.astype(np.float32)
        self._realtime = realtime
        self._then_wait = then_wait  # after the audio, wait forever (like a microphone in a quiet room)

    async def frames(self) -> AsyncIterator[np.ndarray]:
        audio = self._audio
        for start in range(0, len(audio) - FRAME + 1, FRAME):
            yield audio[start : start + FRAME]
            await asyncio.sleep(FRAME / SAMPLE_RATE if self._realtime else 0)
        if self._then_wait:
            await asyncio.Event().wait()


class Listener:
    def __init__(
        self,
        source: AudioSource,
        transcriber: Transcriber,
        gate: HalfDuplexGate,
        settings: ListenSettings,
        on_utterance: Callable[[str], Awaitable[object]],
        *,
        vad: Callable[[np.ndarray], float] | None = None,
    ) -> None:
        self._source = source
        self._transcriber = transcriber
        self._gate = gate
        self._settings = settings
        self._on_utterance = on_utterance
        self._vad = vad

    async def run(self) -> None:
        vad = self._vad or SileroVad()
        segmenter = Segmenter(self._settings)
        start_over = True
        async for frame in self._source.frames():
            if self._gate.muted:
                start_over = True
                continue
            if start_over:
                segmenter.reset()
                if isinstance(vad, SileroVad):
                    vad.reset()
                start_over = False
            utterance = segmenter.feed(frame, vad(frame), rms(frame))
            if utterance is not None:
                await self._transcribe(utterance)

    async def _transcribe(self, utterance: np.ndarray) -> None:
        seconds = len(utterance) / SAMPLE_RATE
        try:
            text = await asyncio.to_thread(self._transcriber.transcribe, utterance)
        except Exception:  # (CancelledError still propagates)
            log.exception("Transcribing %.1f s of speech failed", seconds)
            return
        if not text:
            log.info("Heard %.1f s of sound, but no words", seconds)
            return
        await self._on_utterance(text)
