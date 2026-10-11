"""Mika's voice: GenieTTS on the Acer's CPU (Spike B: a real-time factor of about 0.89).

GenieTTS's own player (tts_async) keeps one global session with queues, a callback and an audio output
stream, and a call that times out can later hand its audio to the next call. So this module runs GenieTTS's
synthesis step itself, in a single worker thread: one sentence at a time, each with a timeout, and a sentence
that times out or is cancelled is stopped through GenieTTS's stop flag. Written against genie-tts 2.0.2 (pinned).

From Phase 0: GENIE_DATA_DIR must be set before GenieTTS is imported (or it waits for input()), and it sets up
logging when imported, so it is imported in load(), after the client's logging.
"""

import asyncio
import base64
import io
import os
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

import numpy as np

from ..config import VoiceSettings

SAMPLE_RATE = 32000  # GenieTTS output: mono, 16-bit PCM
CHARACTER = "mika"


class Voice(Protocol):
    sample_rate: int

    def load(self) -> None:
        """Blocking: run it in a thread."""
        ...

    async def synthesize(self, text: str) -> bytes:
        """16-bit mono PCM at sample_rate."""
        ...


def to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """A complete WAV file around 16-bit mono PCM."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def wav_base64(pcm: bytes, sample_rate: int) -> str:
    return base64.b64encode(to_wav(pcm, sample_rate)).decode("ascii")


def pcm_seconds(pcm: bytes, sample_rate: int) -> float:
    return len(pcm) / 2 / sample_rate


def silence(seconds: float, sample_rate: int) -> bytes:
    return bytes(2 * int(seconds * sample_rate))


class GenieVoice:
    sample_rate = SAMPLE_RATE

    def __init__(self, settings: VoiceSettings) -> None:
        self._settings = settings
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="genie")
        self._client = None  # GenieTTS's synthesis step, once loaded
        self._models = None
        self._reference = None  # the processed reference audio

    def load(self) -> None:
        """Load the voice model and process the reference audio (about 11 s). Blocking: run it in a thread."""
        os.environ["GENIE_DATA_DIR"] = str(self._settings.genie_data_dir)
        import genie_tts
        from genie_tts.Core.Inference import tts_client
        from genie_tts.ModelManager import model_manager
        from genie_tts.Utils.Shared import context

        genie_tts.load_character(
            character_name=CHARACTER, onnx_model_dir=self._settings.voice_model, language=self._settings.language
        )
        genie_tts.set_reference_audio(
            character_name=CHARACTER,
            audio_path=self._settings.ref_voice_path,
            audio_text=self._settings.reference_text(),
            language=self._settings.language,
        )
        self._client, self._models, self._reference = tts_client, model_manager, context.current_prompt_audio

    async def synthesize(self, text: str) -> bytes:
        if self._client is None:
            raise RuntimeError("the voice isn't loaded")
        future = asyncio.get_running_loop().run_in_executor(self._executor, self._synthesize_now, text)
        try:
            async with asyncio.timeout(self._settings.sentence_timeout):
                return await future
        except BaseException:  # timed out or cancelled: stop the sentence still being synthesized
            self._client.stop_event.set()
            raise

    def close(self) -> None:
        """Stop a sentence in progress and let the worker thread end."""
        if self._client is not None:
            self._client.stop_event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _synthesize_now(self, text: str) -> bytes:
        """The step GenieTTS's player runs for one sentence (Core/TTSPlayer.py, _tts_worker_loop)."""
        self._client.stop_event.clear()
        model = self._models.get(CHARACTER)
        audio = self._client.tts(
            text=text,
            prompt_audio=self._reference,
            encoder=model.T2S_ENCODER,
            first_stage_decoder=model.T2S_FIRST_STAGE_DECODER,
            stage_decoder=model.T2S_STAGE_DECODER,
            vocoder=model.VITS,
            prompt_encoder=model.PROMPT_ENCODER,
            language=model.LANGUAGE,
        )
        if audio is None:
            raise RuntimeError("GenieTTS produced no audio")
        return (np.clip(audio.squeeze(), -1.0, 1.0) * 32767).astype(np.int16).tobytes()
