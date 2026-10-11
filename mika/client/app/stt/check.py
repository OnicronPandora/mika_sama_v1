"""Try listening, from mika/client: shows the microphone's level and speech probability twice a second, and
prints what Whisper hears. Nothing is sent to the Mac. Ctrl+C stops it.

    python -m app.stt.check
    python -m app.stt.check --file recording.wav

Use it to set ListenSettings.rms_gate (app/config.py) for your microphone: when you speak, "level" should be
well above the gate; when the room is quiet, below it.
"""

import argparse
import asyncio
import sys
import time
import wave

import numpy as np

from ..config import ListenSettings
from .engine import WhisperTranscriber
from .listener import ArraySource, Microphone
from .vad import SAMPLE_RATE, Segmenter, SileroVad, rms


def read_wav(path: str) -> np.ndarray:
    """A 16-bit WAV file as 16 kHz mono float32."""
    with wave.open(path) as wav:
        rate, channels = wav.getframerate(), wav.getnchannels()
        if wav.getsampwidth() != 2:
            raise SystemExit("Only 16-bit WAV files are supported.")
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        times = np.arange(0, len(audio) / rate, 1 / SAMPLE_RATE)
        audio = np.interp(times, np.arange(len(audio)) / rate, audio).astype(np.float32)
    return audio


async def run(args: argparse.Namespace) -> None:
    settings = ListenSettings()
    print(f"Loading {settings.model} ...", flush=True)
    transcriber = WhisperTranscriber(settings)
    await asyncio.to_thread(transcriber.load)
    if args.file:
        quiet = np.zeros(SAMPLE_RATE, dtype=np.float32)
        source = ArraySource(np.concatenate([quiet, read_wav(args.file), quiet, quiet]))
    else:
        source = Microphone(settings.input_device)
        print(f"Speak now (RMS gate {settings.rms_gate}, speech threshold {settings.speech_threshold}). Ctrl+C stops.")
    vad, segmenter = SileroVad(), Segmenter(settings)
    peak_level = peak_speech = 0.0
    last_report = time.perf_counter()
    async for frame in source.frames():
        level, speech = rms(frame), vad(frame)
        peak_level, peak_speech = max(peak_level, level), max(peak_speech, speech)
        utterance = segmenter.feed(frame, speech, level)
        if not args.file and time.perf_counter() - last_report >= 0.5:
            state = "speaking" if segmenter.speaking else "quiet"
            bar = "#" * min(40, int(peak_level / settings.rms_gate * 4))
            print(f"level {peak_level:.4f} speech {peak_speech:.2f} {state:8} {bar}", flush=True)
            peak_level = peak_speech = 0.0
            last_report = time.perf_counter()
        if utterance is not None:
            started = time.perf_counter()
            text = await asyncio.to_thread(transcriber.transcribe, utterance)
            took = time.perf_counter() - started
            print(f">>> {len(utterance) / SAMPLE_RATE:.1f} s of speech, transcribed in {took:.1f} s: {text or '(no words)'}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", help="a 16-bit WAV file to listen to instead of the microphone")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
