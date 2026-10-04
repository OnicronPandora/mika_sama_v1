from ollama import ChatResponse, Message

from app.config import LLMSettings
from app.llm.engine import LLMEngine, ReplyStats


def part(content: str, **final) -> ChatResponse:
    return ChatResponse(model="llama3.1:8b", message=Message(role="assistant", content=content), done=bool(final), **final)


class FakeOllama:
    """Stands in for ollama.AsyncClient and records the calls."""

    def __init__(self, pieces: list[str]) -> None:
        self.pieces = pieces
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def chat(self, **kwargs):
        self.calls.append(("chat", kwargs))
        if not kwargs.get("stream"):
            return part("", total_duration=1)

        async def stream():
            for piece in self.pieces:
                yield part(piece)
            yield part(
                "",
                load_duration=0,
                prompt_eval_count=400,
                prompt_eval_duration=2_000_000_000,
                eval_count=50,
                eval_duration=5_000_000_000,
            )

        return stream()

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


async def test_stream_chat_reports_ollama_timings():
    stats: list[ReplyStats] = []
    engine = LLMEngine(LLMSettings(), client=FakeOllama(["Hi!"]))
    assert [piece async for piece in engine.stream_chat([], on_stats=stats.append)] == ["Hi!"]
    assert stats == [ReplyStats(load=0, prompt_tokens=400, prompt_time=2.0, reply_tokens=50, reply_time=5.0)]
    assert "prompt 400 tokens in 2.00 s (200 tok/s)" in str(stats[0])
    assert "reply 50 tokens in 5.00 s (10 tok/s)" in str(stats[0])


async def test_load_model_warms_up_with_a_tiny_reply_and_keeps_the_model_loaded():
    client = FakeOllama([])
    await LLMEngine(LLMSettings(), client=client).load_model("You are Mika.")
    name, kwargs = client.calls[0]
    assert name == "chat"
    assert kwargs["messages"] == [{"role": "system", "content": "You are Mika."}]  # caches the system prompt
    assert (kwargs["options"]["num_predict"], kwargs["keep_alive"]) == (1, -1)


async def test_close():
    client = FakeOllama([])
    await LLMEngine(LLMSettings(), client=client).close()
    assert client.closed


async def test_the_real_client_has_timeouts():
    engine = LLMEngine(LLMSettings(read_timeout=45, connect_timeout=3))
    timeout = engine._client._client.timeout  # the httpx client inside ollama.AsyncClient
    assert (timeout.read, timeout.connect) == (45, 3)
    await engine.close()
