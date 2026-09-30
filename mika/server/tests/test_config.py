from app.config import EMBEDDING_DIM, DatabaseSettings, LLMSettings


def make(**overrides) -> DatabaseSettings:
    return DatabaseSettings(_env_file=None, **{"name": "mika", "user": "mika", "password": "s3cret", **overrides})


def test_conninfo():
    info = make(host="db.local", port=5433).conninfo()
    for part in ("host=db.local", "port=5433", "dbname=mika", "user=mika"):
        assert part in info


def test_password_is_hidden():
    settings = make()
    assert "s3cret" not in repr(settings)
    assert "s3cret" not in str(settings)
    assert settings.password.get_secret_value() == "s3cret"


def test_reads_the_environment(monkeypatch):
    env = {"DB_NAME": "a", "DB_USER": "b", "DB_PASSWORD": "c", "DB_HOST": "h", "DB_PORT": "5555", "TEST_DB_NAME": "a_test"}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings = DatabaseSettings(_env_file=None)
    assert (settings.name, settings.user, settings.host, settings.port, settings.test_name) == ("a", "b", "h", 5555, "a_test")


def test_llm_defaults_match_the_spec():
    llm = LLMSettings()
    assert (llm.model, llm.temperature, llm.num_predict) == ("llama3.1:8b", 0.7, 150)


def test_embedding_dim_is_nomic_embed_text():
    assert EMBEDDING_DIM == 768
