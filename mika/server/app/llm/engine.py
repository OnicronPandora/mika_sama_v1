"""Ollama async streaming chat. One client per server, reused for every request (spec)."""

from collections.abc import AsyncIterator, Mapping, Sequence

import httpx
from ollama import AsyncClient

from ..config import LLMSettings


class LLMEngine:
    def __init__(self, settings: LLMSettings, client: AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client or AsyncClient(
            host=settings.ollama_host,
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
        )

    async def load_model(self) -> None:
        """Load the model now (at server startup) rather than on the first message."""
        await self._client.generate(model=self.settings.model, prompt="", keep_alive=self.settings.keep_alive)

    async def stream_chat(self, messages: Sequence[Mapping[str, str]]) -> AsyncIterator[str]:
        """Yield the reply's text as Ollama generates it."""
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

    async def close(self) -> None:
        await self._client.close()
