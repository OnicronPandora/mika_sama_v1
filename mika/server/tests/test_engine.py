from types import SimpleNamespace

from app.config import LLMSettings
from app.llm.engine import LLMEngine


class FakeOllama:
    """Stands in for ollama.AsyncClient and records the calls."""

    def __init__(self, pieces: list[str]) -> None:
        self.pieces = pieces
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def chat(self, **kwargs):
        self.calls.append(("chat", kwargs))

        async def stream():
            for piece in self.pieces:
                yield SimpleNamespace(message=SimpleNamespace(content=piece))

        return stream()

    async def generate(self, **kwargs):
        self.calls.append(("generate", kwargs))

    async def close(self):
        self.closed = True


async def test_stream_chat_yields_the_text_with_the_spec_settings():
    client = FakeOllama(["[happy]", "", " Hi", " there!"])
    engine = LLMEngine(LLMSettings(), client=client)
    messages = [{"role": "user", "content": "Hi Mika!"}]
    assert [piece async for piece in engine.stream_chat(messages)] == ["[happy]", " Hi", " there!"]
    name, kwargs = client.calls[0]
    assert name == "chat"
    assert (kwargs["model"], kwargs["stream"], kwargs["messages"]) == ("llama3.1:8b", True, messages)
    assert kwargs["options"] == {"temperature": 0.7, "num_predict": 150}
    assert kwargs["keep_alive"] == -1


async def test_load_model_keeps_the_model_loaded():
    client = FakeOllama([])
    await LLMEngine(LLMSettings(), client=client).load_model()
    assert client.calls == [("generate", {"model": "llama3.1:8b", "prompt": "", "keep_alive": -1})]


async def test_close():
    client = FakeOllama([])
    await LLMEngine(LLMSettings(), client=client).close()
    assert client.closed


async def test_the_real_client_has_timeouts():
    engine = LLMEngine(LLMSettings(read_timeout=45, connect_timeout=3))
    timeout = engine._client._client.timeout  # the httpx client inside ollama.AsyncClient
    assert (timeout.read, timeout.connect) == (45, 3)
    await engine.close()
