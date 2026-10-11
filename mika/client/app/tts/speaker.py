"""Speaks Mika's approved sentences: GenieTTS turns each one into audio for the avatar page, in order.

One synthesis at a time: while the page plays sentence N, sentence N+1 is being synthesized. Everything for
the avatar page goes through the same queue, so the page gets a turn's emotion, its audio chunks and its
turn_end in that order, after the previous turn's. A sentence that can't be synthesized becomes a short
silence carrying its text, so the page's order (and its transcript line) never breaks.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from mika_shared.enums import Emotion
from mika_shared.events import AudioChunk, ChatServerEvent, ChatTurnEnd, EmotionUpdate

from .engine import Voice, pcm_seconds, silence, wav_base64

log = logging.getLogger(__name__)

FAILED_SENTENCE = 0.3  # seconds of silence sent for a sentence that couldn't be synthesized


@dataclass(frozen=True)
class _Emotion:
    turn_id: str
    emotion: Emotion


@dataclass(frozen=True)
class _Say:
    turn_id: str
    seq: int
    text: str


@dataclass(frozen=True)
class _End:
    turn_id: str
    last_seq: int | None


class Speaker:
    def __init__(
        self,
        voice: Voice,
        send: Callable[[ChatServerEvent], Awaitable[None]],
        on_spoken: Callable[[str, int | None, float], None],
        *,
        ready: asyncio.Event | None = None,
        max_jobs: int = 200,
    ) -> None:
        """send: to the avatar pages. on_spoken(turn_id, last_seq, audio_seconds): the turn's audio has all been sent.
        ready: set once the voice is loaded; sentences wait for it."""
        self._voice = voice
        self._send = send
        self._on_spoken = on_spoken
        self._ready = ready
        self._jobs: asyncio.Queue[_Emotion | _Say | _End] = asyncio.Queue(maxsize=max_jobs)
        self._audio_seconds: dict[str, float] = {}

    def emotion(self, turn_id: str, emotion: Emotion) -> None:
        self._put(_Emotion(turn_id, emotion))

    def say(self, turn_id: str, seq: int, text: str) -> None:
        self._put(_Say(turn_id, seq, text))

    def end(self, turn_id: str, last_seq: int | None) -> None:
        self._put(_End(turn_id, last_seq))

    async def run(self) -> None:
        while True:
            job = await self._jobs.get()
            try:
                await self._do(job)
            except Exception:  # a bad job mustn't stop Mika's voice (CancelledError still propagates)
                log.exception("Speaking %s failed", job)

    def _put(self, job: _Emotion | _Say | _End) -> None:
        try:
            self._jobs.put_nowait(job)
        except asyncio.QueueFull:
            log.error("Too much waiting to be spoken; dropped %s", job)

    async def _do(self, job: _Emotion | _Say | _End) -> None:
        if isinstance(job, _Emotion):
            await self._send(EmotionUpdate(turn_id=job.turn_id, emotion=job.emotion))
        elif isinstance(job, _Say):
            pcm = await self._speak(job.text)
            rate = self._voice.sample_rate
            self._audio_seconds[job.turn_id] = self._audio_seconds.get(job.turn_id, 0.0) + pcm_seconds(pcm, rate)
            await self._send(
                AudioChunk(
                    turn_id=job.turn_id,
                    seq=job.seq,
                    text=job.text,
                    audio_b64=wav_base64(pcm, rate),
                    sample_rate=rate,
                )
            )
        else:
            await self._send(ChatTurnEnd(turn_id=job.turn_id, last_seq=job.last_seq))
            self._on_spoken(job.turn_id, job.last_seq, self._audio_seconds.pop(job.turn_id, 0.0))

    async def _speak(self, text: str) -> bytes:
        try:
            if self._ready is not None:
                await self._ready.wait()
            return await self._voice.synthesize(text)
        except Exception:  # timeout or GenieTTS error (CancelledError still propagates)
            log.exception("Couldn't synthesize %r; sending silence instead", text)
            return silence(FAILED_SENTENCE, self._voice.sample_rate)
