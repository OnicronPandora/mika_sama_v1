import numpy as np
from faster_whisper.vad import get_vad_model

from app.config import ListenSettings
from app.stt.vad import FRAME, FRAME_SECONDS, SAMPLE_RATE, Segmenter, SileroVad, rms


def test_frame_by_frame_matches_faster_whisper_on_a_whole_recording():
    rng = np.random.default_rng(0)
    times = np.arange(FRAME * 40) / SAMPLE_RATE
    audio = (0.3 * np.sin(2 * np.pi * 180 * times) * (1 + np.sin(2 * np.pi * 3 * times)) + 0.02 * rng.standard_normal(len(times)))
    audio = audio.astype(np.float32)
    whole = get_vad_model()(audio).reshape(-1)  # faster-whisper's own run over the recording
    vad = SileroVad()
    frames = [vad(audio[i : i + FRAME]) for i in range(0, len(audio), FRAME)]
    assert np.allclose(frames, whole, atol=1e-4)
    vad.reset()
    assert abs(vad(audio[:FRAME]) - whole[0]) < 1e-4  # reset starts over


def test_rms():
    assert rms(np.zeros(FRAME, dtype=np.float32)) == 0
    sine = np.sin(2 * np.pi * np.arange(FRAME) * 8 / FRAME).astype(np.float32)
    assert abs(rms(0.5 * sine) - 0.5 / np.sqrt(2)) < 1e-3


SETTINGS = ListenSettings(start_speech=0.1, end_silence=0.3, pre_roll=0.2, min_utterance=0.3, max_utterance=2.0, rms_gate=0.01)


def feed(segmenter: Segmenter, pattern: list[tuple[float, float, float]]) -> list[np.ndarray]:
    """pattern: (seconds, speech probability, level) runs. Frames are numbered so utterances can be checked."""
    utterances, number = [], 0
    for seconds, prob, level in pattern:
        for _ in range(round(seconds / FRAME_SECONDS)):
            frame = np.full(FRAME, number, dtype=np.float32)
            number += 1
            if (utterance := segmenter.feed(frame, prob, level)) is not None:
                utterances.append(utterance[::FRAME].astype(int))  # the frame numbers in the utterance
    return utterances


def test_an_utterance_keeps_a_little_before_and_after():
    (utterance,) = feed(Segmenter(SETTINGS), [(1.0, 0.0, 0.1), (1.0, 0.9, 0.1), (1.0, 0.0, 0.1)])
    first_speech = round(1.0 / FRAME_SECONDS)
    pre_roll, tail = round(0.2 / FRAME_SECONDS), round(Segmenter.TAIL / FRAME_SECONDS)
    assert utterance[0] == first_speech - pre_roll
    assert utterance[-1] == 2 * first_speech - 1 + tail


def test_a_short_pause_doesnt_end_it_but_a_long_one_does():
    pattern = [(0.5, 0.9, 0.1), (0.2, 0.0, 0.1), (0.5, 0.9, 0.1), (0.5, 0.0, 0.1), (0.5, 0.9, 0.1), (0.5, 0.0, 0.1)]
    assert len(feed(Segmenter(SETTINGS), pattern)) == 2


def test_too_short_is_dropped_and_too_long_is_cut():
    assert feed(Segmenter(SETTINGS), [(0.2, 0.9, 0.1), (1.0, 0.0, 0.1)]) == []  # a click
    long = feed(Segmenter(SETTINGS), [(5.0, 0.9, 0.1)])
    assert len(long) == 2 and all(len(u) <= round(2.0 / FRAME_SECONDS) for u in long)


def test_quiet_frames_are_silence_whatever_the_vad_says():
    assert feed(Segmenter(SETTINGS), [(1.0, 0.9, 0.001), (1.0, 0.0, 0.1)]) == []  # below the RMS gate
    # In between the thresholds, a frame neither starts nor ends speech.
    (utterance,) = feed(Segmenter(SETTINGS), [(0.5, 0.9, 0.1), (1.0, 0.4, 0.1), (0.5, 0.0, 0.1)])
    assert len(utterance) > round(1.4 / FRAME_SECONDS)
