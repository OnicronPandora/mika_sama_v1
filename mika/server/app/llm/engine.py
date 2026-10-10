"""Ollama async streaming chat. One client per server, reused for every request (spec)."""

import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import aclosing
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


# Told about every finished call: its label ("reply", "classify", ...), Ollama's timings and the wall time.
CallListener = Callable[[str, ReplyStats, float], None]


class LLMEngine:
    def __init__(
        self, settings: LLMSettings, client: AsyncClient | None = None, *, on_call: CallListener | None = None
    ) -> None:
        self.settings = settings
        self.on_call = on_call
        self._client = client or AsyncClient(
            host=settings.ollama_host,
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
        )

    async def warm_up(self, messages: Sequence[Mapping[str, str]], *, label: str = "warm-up") -> None:
        """Run a one-token reply, so Ollama loads the model if needed and keeps these messages in its cache.

        A later prompt that starts with the same messages only has to read what comes after them.
        """
        start = time.perf_counter()
        response = await self._client.chat(
            model=self.settings.model,
            messages=list(messages),
            options={"temperature": self.settings.temperature, "num_predict": 1},
            keep_alive=self.settings.keep_alive,
        )
        self._report(label, ReplyStats.from_response(response), start)

    async def load_model(self, system_prompt: str = "") -> None:
        """Load the model and run one tiny reply, so the first real reply doesn't pay for the model's first pass.

        Given the system prompt, Ollama also keeps it cached for the first turn.
        """
        messages = [{"role": "system", "content": system_prompt}] if system_prompt else [{"role": "user", "content": "Hi"}]
        await self.warm_up(messages, label="load")

    async def stream_chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        on_stats: Callable[[ReplyStats], None] | None = None,
        label: str = "reply",
    ) -> AsyncIterator[str]:
        """Yield the reply's text as Ollama generates it. on_stats gets Ollama's timings at the end.

        Closing the iterator early (aclose, or contextlib.aclosing) closes the connection, and Ollama stops
        generating.
        """
        start = time.perf_counter()
        stream = await self._client.chat(
            model=self.settings.model,
            messages=list(messages),
            stream=True,
            options=self._options(self.settings.temperature, self.settings.num_predict),
            keep_alive=self.settings.keep_alive,
        )
        async with aclosing(stream):
            async for part in stream:
                if part.message.content:
                    yield part.message.content
                if part.done:
                    stats = ReplyStats.from_response(part)
                    if on_stats:
                        on_stats(stats)
                    self._report(label, stats, start)

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float,
        num_predict: int,
        json_schema: dict | None = None,
        label: str = "complete",
    ) -> str:
        """One whole reply without streaming, for the output filter's classifier and replacer calls."""
        start = time.perf_counter()
        response = await self._client.chat(
            model=self.settings.model,
            messages=list(messages),
            format=json_schema,
            options=self._options(temperature, num_predict),
            keep_alive=self.settings.keep_alive,
        )
        self._report(label, ReplyStats.from_response(response), start)
        return response.message.content or ""

    async def close(self) -> None:
        await self._client.close()

    def _options(self, temperature: float, num_predict: int) -> dict:
        options = {"temperature": temperature, "num_predict": num_predict}
        if self.settings.seed is not None:
            options["seed"] = self.settings.seed
        return options

    def _report(self, label: str, stats: ReplyStats, start: float) -> None:
        if self.on_call:
            self.on_call(label, stats, time.perf_counter() - start)
