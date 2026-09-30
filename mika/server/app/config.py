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


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
