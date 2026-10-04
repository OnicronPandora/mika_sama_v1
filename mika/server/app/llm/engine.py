"""Ollama async streaming chat. One client per server, reused for every request (spec)."""

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass

import httpx
from ollama import AsyncClient, ChatResponse

from ..config import LLMSettings


@dataclass(frozen=True)
class ReplyStats:
    """Ollama's own timings for one reply, in seconds."""

    load: float
    prompt_tokens: int
    prompt_time: float
    reply_tokens: int
    reply_time: float

    @classmethod
    def from_response(cls, response: ChatResponse) -> "ReplyStats":
        def seconds(nanoseconds: int | None) -> float:
            return (nanoseconds or 0) / 1e9

        return cls(
            load=seconds(response.load_duration),
            prompt_tokens=response.prompt_eval_count or 0,
            prompt_time=seconds(response.prompt_eval_duration),
            reply_tokens=response.eval_count or 0,
            reply_time=seconds(response.eval_duration),
        )

    def __str__(self) -> str:
        def rate(tokens: int, seconds: float) -> str:
            return f"{tokens / seconds:.0f} tok/s" if seconds else "-"

        return (
            f"model load {self.load:.2f} s | prompt {self.prompt_tokens} tokens in {self.prompt_time:.2f} s "
            f"({rate(self.prompt_tokens, self.prompt_time)}) | reply {self.reply_tokens} tokens in "
            f"{self.reply_time:.2f} s ({rate(self.reply_tokens, self.reply_time)})"
        )


class LLMEngine:
    def __init__(self, settings: LLMSettings, client: AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client or AsyncClient(
            host=settings.ollama_host,
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
        )

    async def load_model(self, system_prompt: str = "") -> None:
        """Load the model and run one tiny reply, so the first real reply doesn't pay for the model's first pass.

        Given the system prompt, Ollama also keeps it cached for the first turn.
        """
        messages = [{"role": "system", "content": system_prompt}] if system_prompt else [{"role": "user", "content": "Hi"}]
        await self._client.chat(
            model=self.settings.model,
            messages=messages,
            options={"temperature": self.settings.temperature, "num_predict": 1},
            keep_alive=self.settings.keep_alive,
        )

    async def stream_chat(
        self, messages: Sequence[Mapping[str, str]], *, on_stats: Callable[[ReplyStats], None] | None = None
    ) -> AsyncIterator[str]:
        """Yield the reply's text as Ollama generates it. on_stats gets Ollama's timings at the end."""
        stream = await self._client.chat(
            model=self.settings.model,
            messages=list(messages),
            stream=True,
            options={"temperature": self.settings.temperature, "num_predict": self.settings.num_predict},
            keep_alive=self.settings.keep_alive,
        )
        async for part in stream:
            if part.message.content:
                yield part.message.content
            if part.done and on_stats:
                on_stats(ReplyStats.from_response(part))

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float,
        num_predict: int,
        json_schema: dict | None = None,
    ) -> str:
        """One whole reply without streaming, for the output filter's classifier and replacer calls."""
        response = await self._client.chat(
            model=self.settings.model,
            messages=list(messages),
            format=json_schema,
            options={"temperature": temperature, "num_predict": num_predict},
            keep_alive=self.settings.keep_alive,
        )
        return response.message.content or ""

    async def close(self) -> None:
        await self._client.close()
