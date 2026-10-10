"""Server configuration.

Database settings come from the environment or mika/server/.env (git-ignored; see .env.example).
LLM settings are Python defaults from the spec (docs/top_secret.md).
"""

from pathlib import Path
from typing import Literal

from psycopg.conninfo import make_conninfo
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = SERVER_DIR / ".env"

# nomic-embed-text; must match the vector(768) column in scripts/setup_db.sql.
EMBEDDING_DIM = 768


class DatabaseSettings(BaseSettings):
    """DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, plus TEST_DB_NAME for the tests."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_prefix="DB_", extra="ignore", frozen=True)

    name: str
    user: str
    password: SecretStr
    host: str = "localhost"
    port: int = 5432
    test_name: str | None = Field(default=None, validation_alias="TEST_DB_NAME")

    def conninfo(self) -> str:
        return make_conninfo(
            host=self.host,
            port=self.port,
            dbname=self.name,
            user=self.user,
            password=self.password.get_secret_value(),
        )


class LLMSettings(BaseModel):
    """Ollama chat settings from the spec."""

    model_config = ConfigDict(frozen=True)

    ollama_host: str = "http://localhost:11434"
    model: str = "llama3.1:8b"
    temperature: float = 0.7
    num_predict: int = 150
    # -1 keeps the model loaded while Ollama runs, so a quiet stream never pays the 6-7 s reload (Spike A).
    keep_alive: float | str = -1
    connect_timeout: float = 5.0
    read_timeout: float = 60.0  # longest wait for the next piece of a reply before giving up
    reply_timeout: float = 60.0  # one whole reply, prompt included (150 tokens at 10-11 tokens/s on the Mac)
    warm_up_timeout: float = 60.0  # loading the model (6-7 s) and reading a prompt, at startup and between turns
    seed: int | None = None  # fixed sampling for measurements (app.turn.bench); None in normal use


class FilterSettings(BaseModel):
    """Output filter settings. On a timeout the classifier fails closed (spec: REPLACE)."""

    model_config = ConfigDict(frozen=True)

    classifier_timeout: float = 12.0  # Spike A: 2-5 s per sentence on the Mac
    classifier_num_predict: int = 60
    replacer_timeout: float = 12.0
    replacer_num_predict: int = 60
    filtered_prefix: str = "Filtered!"  # spoken before the LLM's line on REPLACE (spec)
    # How the classifier and the replacer see the turn (Phase 6 experiment; compare with python -m app.turn.bench):
    # - "separate": their own short prompts (Phase 4). Ollama has to read Mika's prompt again after them.
    # - "shared": they continue Mika's own conversation, so Ollama reuses the prompt it already read for her reply.
    context_mode: Literal["separate", "shared"] = "separate"


class MemorySettings(BaseModel):
    """Recent turns (FIFO) and long-term memories (RAG).

    Kept small on purpose: on the Mac, Ollama re-reads the prompt at about 84 tokens/s, so every 100 tokens
    of history or memories delays Mika's reply by about 1.2 s (Phase 4 measurements).
    """

    model_config = ConfigDict(frozen=True)

    admin_name: str = "Pandora"  # how the admin (user_id "admin") is named in memories and filter context
    history_turns: int = 6  # turns kept per user in the FIFO cache
    # Budget for recent turns in the chat prompt. The window of turns grows until it no longer fits, then restarts
    # with the newest turns that fit in half of it (ConversationCache.window).
    history_max_tokens: int = 350
    classifier_history_turns: int = 2  # recent turns the output filter sees as context
    memory_count: int = 3  # long-term memories recalled per turn
    # Cosine distance; less similar memories are ignored. Calibrated 2026-10-04 on a small sample with the
    # quantized model: related memories scored 0.29-0.47, unrelated 0.44-0.60. Re-tune with real conversations.
    memory_max_distance: float = 0.45
    memory_max_tokens: int = 150
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5-Q"  # quantized nomic-embed-text, 0.13 GB, 768 dims
    embedding_cache_dir: Path = SERVER_DIR / ".cache" / "fastembed"
    embedding_threads: int = 2  # CPU threads for embeddings; leaves the rest for Ollama


class ServerSettings(BaseModel):
    """The server process and /ws/runtime (run it with python -m app)."""

    model_config = ConfigDict(frozen=True)

    host: str = "0.0.0.0"  # the Acer connects over the local network
    port: int = 8000
    # Browser pages allowed to open /ws/runtime or call the HTTP API (CORS doesn't cover WebSockets, so the
    # endpoint checks Origin itself). The Acer's Python client sends no Origin header and needs no entry.
    allowed_origins: tuple[str, ...] = ()
    max_pending_messages: int = 4  # messages waiting while Mika answers; more are refused
    send_timeout: float = 10.0  # a send that takes longer means the Acer is gone
    graceful_shutdown_timeout: float = 5.0  # uvicorn's limit for open connections at shutdown
    log_file: Path = SERVER_DIR / "server.log"  # spec: logs are stored in server.log


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    filter: FilterSettings = Field(default_factory=FilterSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
