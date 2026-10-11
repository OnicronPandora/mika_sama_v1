import asyncio
import os

import numpy as np
import pytest
from fakes import FakeTranscriber, fake_vad, quiet, speech

from app.config import CLIENT_DIR, ListenSettings
from app.stt.check import read_wav
from app.stt.engine import WhisperTranscriber
from app.stt.gate import HalfDuplexGate
from app.stt.listener import ArraySource, Listener

SETTINGS = ListenSettings(end_silence=0.3, min_utterance=0.3)


async def listen(audio: np.ndarray, transcriber: FakeTranscriber, gate: HalfDuplexGate | None = None) -> list[str]:
    said: list[str] = []

    async def on_utterance(text: str) -> None:
        said.append(text)

    gate = gate or HalfDuplexGate(echo_guard=0)
    listener = Listener(ArraySource(audio), transcriber, gate, SETTINGS, on_utterance, vad=fake_vad)
    await listener.run()
    return said


async def test_each_utterance_is_transcribed_and_passed_on():
    transcriber = FakeTranscriber("Hi Mika!", "How are you?")
    audio = np.concatenate([quiet(0.5), speech(1.0), quiet(1.0), speech(0.8), quiet(1.0)])
    assert await listen(audio, transcriber) == ["Hi Mika!", "How are you?"]
    assert transcriber.heard[0] == pytest.approx(1.0 + 0.3 + 0.2, abs=0.1)  # speech + pre-roll + tail


async def test_noise_without_words_is_not_passed_on():
    assert await listen(np.concatenate([speech(1.0), quiet(1.0)]), FakeTranscriber("")) == []


async def test_nothing_is_heard_while_muted():
    gate = HalfDuplexGate(echo_guard=0)
    gate.message_sent()  # Mika is answering
    transcriber = FakeTranscriber("Hi Mika!")
    assert await listen(np.concatenate([speech(1.0), quiet(1.0)]), transcriber, gate) == []
    assert transcriber.heard == []


async def test_a_transcription_error_doesnt_stop_listening():
    class Flaky(FakeTranscriber):
        def transcribe(self, audio):
            if not self.heard:
                self.heard.append(0)
                raise RuntimeError("whisper broke")
            return super().transcribe(audio)

    audio = np.concatenate([speech(1.0), quiet(1.0), speech(1.0), quiet(1.0)])
    assert await listen(audio, Flaky("Second try.")) == ["Second try."]


REFERENCE = CLIENT_DIR.parents[1] / "others" / "voice" / "ref_data" / "55.wav"


@pytest.mark.skipif(not os.environ.get("MIKA_TEST_STT"), reason="set MIKA_TEST_STT=1 (loads Whisper small.en)")
async def test_whisper_hears_the_reference_voice():
    transcriber = WhisperTranscriber(ListenSettings())
    await asyncio.to_thread(transcriber.load)
    text = await asyncio.to_thread(transcriber.transcribe, read_wav(str(REFERENCE)))
    assert "pandora" in text.lower() and "joking" in text.lower()
