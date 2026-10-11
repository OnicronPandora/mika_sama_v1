import asyncio
import base64
import io
import os
import wave

import pytest
from fakes import HANG, FakeVoice

from app.config import VoiceSettings
from app.tts.engine import GenieVoice, pcm_seconds, to_wav
from app.tts.speaker import FAILED_SENTENCE, Speaker
from mika_shared.enums import Emotion
from mika_shared.events import AudioChunk, ChatTurnEnd, EmotionUpdate


def test_wav_round_trip():
    pcm = bytes(range(256)) * 10
    with wave.open(io.BytesIO(to_wav(pcm, 32000))) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 32000)
        assert wav.readframes(wav.getnframes()) == pcm
    assert pcm_seconds(bytes(64000), 32000) == 1.0


class Spoken:
    """What the speaker sent to the avatar pages, and the turns it reported as spoken."""

    def __init__(self) -> None:
        self.events: list = []
        self.turns: list[tuple[str, int | None, float]] = []

    async def send(self, event) -> None:
        self.events.append(event)

    def on_spoken(self, turn_id, last_seq, audio_seconds) -> None:
        self.turns.append((turn_id, last_seq, audio_seconds))


async def speak(jobs, voice=None, ready=None) -> tuple[Spoken, FakeVoice]:
    voice = voice or FakeVoice()
    spoken = Spoken()
    speaker = Speaker(voice, spoken.send, spoken.on_spoken, ready=ready)
    task = asyncio.create_task(speaker.run())
    for name, *args in jobs:
        getattr(speaker, name)(*args)
    async with asyncio.timeout(5):
        while len(spoken.turns) < sum(1 for name, *_ in jobs if name == "end"):
            await asyncio.sleep(0.01)
    task.cancel()
    return spoken, voice


async def test_a_turn_reaches_the_page_in_order():
    spoken, _ = await speak([("emotion", "t1", Emotion.HAPPY), ("say", "t1", 0, "Hi!"), ("say", "t1", 1, "Bye now."), ("end", "t1", 1)])
    emotion, first, second, end = spoken.events
    assert emotion == EmotionUpdate(turn_id="t1", emotion=Emotion.HAPPY)
    assert (first.seq, first.text, second.seq, second.text) == (0, "Hi!", 1, "Bye now.")
    assert isinstance(first, AudioChunk) and first.sample_rate == 32000
    with wave.open(io.BytesIO(base64.b64decode(first.audio_b64))) as wav:
        assert wav.getnframes() == int(0.05 * 3 * 32000)  # FakeVoice: 0.05 s per character
    assert end == ChatTurnEnd(turn_id="t1", last_seq=1)
    assert spoken.turns == [("t1", 1, pytest.approx(0.05 * (3 + 8)))]


async def test_a_sentence_that_fails_becomes_silence_with_its_text():
    spoken, _ = await speak([("say", "t1", 0, "fail"), ("say", "t1", 1, "Okay."), ("end", "t1", 1)])
    failed, ok, _ = spoken.events
    assert (failed.seq, failed.text, ok.seq) == (0, "fail", 1)
    with wave.open(io.BytesIO(base64.b64decode(failed.audio_b64))) as wav:
        assert wav.getnframes() == int(FAILED_SENTENCE * 32000)


async def test_sentences_wait_for_the_voice_to_load():
    ready = asyncio.Event()
    voice, spoken = FakeVoice(), Spoken()
    speaker = Speaker(voice, spoken.send, spoken.on_spoken, ready=ready)
    task = asyncio.create_task(speaker.run())
    speaker.say("t1", 0, "Hi!")
    speaker.end("t1", 0)
    await asyncio.sleep(0.05)
    assert voice.spoken == []  # still loading
    ready.set()
    async with asyncio.timeout(5):
        while not spoken.turns:
            await asyncio.sleep(0.01)
    task.cancel()
    assert voice.spoken == ["Hi!"]


async def test_cancelling_stops_a_sentence_in_progress():
    voice = FakeVoice()
    spoken = Spoken()
    speaker = Speaker(voice, spoken.send, spoken.on_spoken)
    task = asyncio.create_task(speaker.run())
    speaker.say("t1", 0, HANG)
    while not voice.spoken:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert spoken.events == []


@pytest.mark.skipif(not os.environ.get("MIKA_TEST_VOICE"), reason="set MIKA_TEST_VOICE=1 (loads GenieTTS, about 15 s)")
async def test_the_real_voice():
    voice = GenieVoice(VoiceSettings())
    await asyncio.to_thread(voice.load)
    try:
        pcm = await voice.synthesize("Hi Pandora!")
        assert pcm_seconds(pcm, voice.sample_rate) > 0.5
    finally:
        voice.close()
