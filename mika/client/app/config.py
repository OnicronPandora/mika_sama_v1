"""Client configuration (Python, spec: SERVER_WS_URL, VOICE_MODEL, REF_VOICE_PATH, REF_TEXT).

The client runs on the Acer. The voice files live in others/voice (git-ignored; each machine keeps its own
copy), and the Whisper model is downloaded into mika/client/.cache on first use.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

CLIENT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = CLIENT_DIR.parents[1]
VOICE_DIR = PROJECT_DIR / "others" / "voice"


class VoiceSettings(BaseModel):
    """Mika's voice: GenieTTS with the mikav3 model and its reference audio (Spike B)."""

    model_config = ConfigDict(frozen=True)

    voice_model: Path = VOICE_DIR / "mikav3_onnx_model"  # spec: VOICE_MODEL
    ref_voice_path: Path = VOICE_DIR / "ref_data" / "55.wav"  # spec: REF_VOICE_PATH
    ref_text: str | None = None  # spec: REF_TEXT; None reads it from the .txt next to the reference audio
    genie_data_dir: Path = VOICE_DIR / "GenieData"
    language: str = "en"
    sentence_timeout: float = 30.0  # one sentence takes 1.5-5 s on the Acer (Spike B)

    def reference_text(self) -> str:
        if self.ref_text is not None:
            return self.ref_text
        return self.ref_voice_path.with_suffix(".txt").read_text(encoding="utf-8").strip()


class ListenSettings(BaseModel):
    """Speech-to-text: silero-vad and an RMS noise gate find speech, faster-whisper transcribes it (decision #20).

    Silence and noise levels depend on the microphone: tune them with python -m app.stt.check.
    """

    model_config = ConfigDict(frozen=True)

    model: str = "small.en"  # chosen 2026-10-11; downloaded once (486 MB)
    compute_type: str = "int8"
    cpu_threads: int = 4
    beam_size: int = 5
    model_dir: Path = CLIENT_DIR / ".cache" / "whisper"
    input_device: int | str | None = None  # None: the system's default microphone
    speech_threshold: float = 0.5  # Silero probability from which a frame counts as speech
    silence_threshold: float = 0.35  # below this a frame counts as silence (in between: no change)
    rms_gate: float = 0.005  # frames quieter than this count as silence, whatever the VAD says
    start_speech: float = 0.1  # seconds of speech that start an utterance
    end_silence: float = 0.7  # seconds of silence that end it
    pre_roll: float = 0.3  # seconds kept from before the start, so the first word isn't cut
    min_utterance: float = 0.5  # shorter ones (clicks, coughs) are dropped
    max_utterance: float = 15.0  # longer ones are sent at this length
    echo_guard: float = 0.5  # seconds the mic stays muted after Mika's last audio ends
    playback_margin: float = 10.0  # extra wait for the avatar page's playback report before unmuting anyway


class ClientSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    server_ws_url: str = "ws://Pandoras-MacBook-Pro.local:8000/ws/runtime"  # spec: SERVER_WS_URL
    host: str = "127.0.0.1"  # /ws/chat serves the browser pages on this machine only
    port: int = 8001
    # Pages allowed to open /ws/chat: the Vite dev server (Phase 9) in Chrome and in OBS's browser source.
    allowed_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    send_timeout: float = 10.0
    reconnect_max_delay: float = 10.0
    graceful_shutdown_timeout: float = 5.0
    log_file: Path = CLIENT_DIR / "client.log"
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    listen: ListenSettings = Field(default_factory=ListenSettings)
