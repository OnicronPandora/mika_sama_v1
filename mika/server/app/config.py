"""Server configuration.

Database settings come from the environment or mika/server/.env (git-ignored; see .env.example).
LLM settings are Python defaults from the spec (docs/top_secret.md).
"""

from pathlib import Path

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


class FilterSettings(BaseModel):
    """Output filter settings. On a timeout the classifier fails closed (spec: REPLACE)."""

    model_config = ConfigDict(frozen=True)

    classifier_timeout: float = 12.0  # Spike A: 2-5 s per sentence on the Mac
    classifier_num_predict: int = 60
    replacer_timeout: float = 12.0
    replacer_num_predict: int = 60
    filtered_prefix: str = "Filtered!"  # spoken before the LLM's line on REPLACE (spec)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    filter: FilterSettings = Field(default_factory=FilterSettings)
