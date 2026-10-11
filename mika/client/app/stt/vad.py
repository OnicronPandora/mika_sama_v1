"""Finding speech in the microphone's stream (decision #20): silero-vad, with RMS as a noise gate.

Audio arrives in frames of 512 samples at 16 kHz (32 ms), the size silero-vad works on. Silero's model is the
ONNX file that faster-whisper ships (no PyTorch needed); faster-whisper runs it over a whole recording at once,
and SileroVad runs it one frame at a time, carrying its state from frame to frame.

The Segmenter turns frames into utterances: speech starts after a short run of speech frames, ends after a
run of silence, keeps a little audio from before the start, and drops what is too short to be words.
"""

import os
from collections import deque

import numpy as np

from ..config import ListenSettings

SAMPLE_RATE = 16000  # what silero-vad and Whisper expect
FRAME = 512  # samples per frame (32 ms)
FRAME_SECONDS = FRAME / SAMPLE_RATE
_CONTEXT = 64  # samples of the previous frame that silero-vad sees with each frame


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))


class SileroVad:
    """Speech probability per frame."""

    def __init__(self) -> None:
        import onnxruntime
        from faster_whisper.utils import get_assets_path

        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            os.path.join(get_assets_path(), "silero_vad_v6.onnx"),
            providers=["CPUExecutionProvider"],
            sess_options=options,
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(_CONTEXT, dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        audio = np.concatenate([self._context, frame.astype(np.float32, copy=False)])[np.newaxis, :]
        probs, self._h, self._c = self._session.run(None, {"input": audio, "h": self._h, "c": self._c})
        self._context = audio[0, -_CONTEXT:]
        return float(probs[0])


class Segmenter:
    """Frames in, finished utterances out."""

    TAIL = 0.2  # seconds of the closing silence kept, so the last word isn't cut off

    def __init__(self, settings: ListenSettings) -> None:
        self._settings = settings
        self._start_frames = max(1, round(settings.start_speech / FRAME_SECONDS))
        self._end_frames = max(1, round(settings.end_silence / FRAME_SECONDS))
        self._min_frames = round(settings.min_utterance / FRAME_SECONDS)
        self._max_frames = round(settings.max_utterance / FRAME_SECONDS)
        self._tail_frames = round(self.TAIL / FRAME_SECONDS)
        # The frames before an utterance starts: the pre-roll, then the run of speech that starts it.
        self._before: deque[np.ndarray] = deque(maxlen=round(settings.pre_roll / FRAME_SECONDS) + self._start_frames)
        self.reset()

    @property
    def speaking(self) -> bool:
        return self._utterance is not None

    def reset(self) -> None:
        self._before.clear()
        self._utterance: list[np.ndarray] | None = None
        self._lead = 0  # pre-roll frames at the start of the utterance
        self._speech_run = 0  # consecutive speech frames before an utterance starts
        self._silence_run = 0  # consecutive silent frames inside an utterance

    def feed(self, frame: np.ndarray, speech_prob: float, level: float) -> np.ndarray | None:
        """Add one frame. Returns an utterance (16 kHz float32) when one has just ended, else None."""
        settings = self._settings
        speech = speech_prob >= settings.speech_threshold and level >= settings.rms_gate
        silence = speech_prob < settings.silence_threshold or level < settings.rms_gate

        if self._utterance is None:
            self._before.append(frame)
            self._speech_run = self._speech_run + 1 if speech else 0
            if self._speech_run >= self._start_frames:
                self._utterance = list(self._before)
                self._lead = len(self._utterance) - self._speech_run
                self._before.clear()
                self._silence_run = 0
            return None

        self._utterance.append(frame)
        self._silence_run = self._silence_run + 1 if silence else 0
        if self._silence_run < self._end_frames and len(self._utterance) < self._max_frames:
            return None
        tail = min(self._silence_run, self._tail_frames)
        frames = self._utterance[: len(self._utterance) - (self._silence_run - tail)]
        spoken = len(frames) - self._lead - tail
        self.reset()
        return np.concatenate(frames) if spoken >= self._min_frames else None
