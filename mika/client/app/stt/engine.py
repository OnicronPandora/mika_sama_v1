"""Speech to text: faster-whisper on the CPU, int8 (decision #20), English (small.en, chosen 2026-10-11).

The utterances come already cut by the voice activity detector, so Whisper's own VAD filter is off. Whisper
can invent words for noise ("Thank you."), so segments it marks as probably not speech are dropped.
"""

from typing import Protocol

import numpy as np

from ..config import ListenSettings

NO_SPEECH = 0.6  # segments Whisper rates likelier than this to be no speech are dropped


class Transcriber(Protocol):
    def load(self) -> None:
        """Blocking: run it in a thread."""
        ...

    def transcribe(self, audio: np.ndarray) -> str:
        """16 kHz float32 mono in, text out ("" when nothing was said). Blocking: run it in a thread."""
        ...


class WhisperTranscriber:
    def __init__(self, settings: ListenSettings) -> None:
        self._settings = settings
        self._model = None

    def load(self) -> None:
        """Load the model; the first time, download it (small.en: 486 MB). Blocking: run it in a thread."""
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            self._settings.model,
            device="cpu",
            compute_type=self._settings.compute_type,
            cpu_threads=self._settings.cpu_threads,
            download_root=str(self._settings.model_dir),
        )

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("the speech-to-text model isn't loaded")
        segments, _ = self._model.transcribe(
            audio,
            language="en",
            beam_size=self._settings.beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        texts = [segment.text.strip() for segment in segments if segment.no_speech_prob < NO_SPEECH]
        text = " ".join(text for text in texts if text)
        return text if any(char.isalnum() for char in text) else ""
