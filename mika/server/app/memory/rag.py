"""Long-term memory (spec: Embedding Vector, RAG): every turn is embedded and stored, and the memories most
similar to a new message are recalled into the prompt.

Embeddings come from nomic-embed-text running on the Mac's CPU inside the server, through fastembed and ONNX
Runtime, not through Ollama, so they never unload llama3.1:8b (decision #23). nomic-embed-text expects a task
prefix on every text; fastembed doesn't add it, so this module does.
"""

import asyncio
from collections.abc import Collection, Sequence
from typing import Protocol

import numpy as np
from psycopg import AsyncConnection

from ..config import MemorySettings
from ..db import queries
from .turns import estimate_tokens

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

MEMORIES_HEADER = "[Things you remember from earlier conversations (they may be old):"


class Embedder(Protocol):
    async def embed_document(self, text: str) -> np.ndarray: ...
    async def embed_query(self, text: str) -> np.ndarray: ...


class LocalEmbedder:
    """nomic-embed-text through fastembed. The model (0.13 GB) is downloaded on first load."""

    def __init__(self, settings: MemorySettings) -> None:
        self._settings = settings
        self._model = None
        self._lock = asyncio.Lock()  # one ONNX run at a time

    def load(self) -> None:
        """Load (and on first use download) the model. Blocking: call it in a thread at startup."""
        if self._model is None:
            from fastembed import TextEmbedding  # imported here: it is slow to import

            self._model = TextEmbedding(
                model_name=self._settings.embedding_model,
                cache_dir=str(self._settings.embedding_cache_dir),
                threads=self._settings.embedding_threads,
            )

    async def embed_document(self, text: str) -> np.ndarray:
        return await self._embed(DOCUMENT_PREFIX + text)

    async def embed_query(self, text: str) -> np.ndarray:
        return await self._embed(QUERY_PREFIX + text)

    async def _embed(self, text: str) -> np.ndarray:
        async with self._lock:
            return await asyncio.to_thread(self._embed_now, text)

    def _embed_now(self, text: str) -> np.ndarray:
        self.load()
        return next(iter(self._model.embed([text])))


class MemoryStore:
    def __init__(self, embedder: Embedder, settings: MemorySettings, *, assistant: str) -> None:
        self._embedder = embedder
        self._settings = settings
        self._assistant = assistant  # Mika's name in the stored text

    async def remember(
        self, conn: AsyncConnection, *, chat_log_id: int, speaker: str, user_message: str, reply: str
    ) -> int:
        """Store one turn. The prompt gets it with names; the embedding is made without them, because the
        shared "Pandora: ... Mika-sama: ..." frame makes every memory look alike (measured 2026-10-04)."""
        content = f"{speaker}: {user_message}\n{self._assistant}: {reply}"
        embedding = await self._embedder.embed_document(f"{user_message} {reply}")
        return await queries.insert_memory(conn, chat_log_id=chat_log_id, content=content, embedding=embedding)

    async def recall(
        self, conn: AsyncConnection, query: str, *, exclude_chat_log_ids: Collection[int] = ()
    ) -> list[str]:
        """The most similar memories, nearest first. Turns still in the recent history are skipped."""
        embedding = await self._embedder.embed_query(query)
        matches = await queries.nearest_memories(
            conn, embedding, limit=self._settings.memory_count + len(exclude_chat_log_ids)
        )
        close = [
            match.content
            for match in matches
            if match.chat_log_id not in exclude_chat_log_ids and match.distance <= self._settings.memory_max_distance
        ]
        return close[: self._settings.memory_count]


def memories_block(memories: Sequence[str], max_tokens: int) -> str | None:
    """Recalled memories as a block for the start of the user's message, nearest first, within the budget.

    None if there are none. (Not a system message: Ollama would move it to the top of the prompt, and the
    memories change every turn, so nothing after the system prompt could be reused from Ollama's cache.)
    """
    lines: list[str] = []
    for memory in memories:
        candidate = [*lines, "- " + memory.replace("\n", " / ")]
        if estimate_tokens(_render(candidate)) > max_tokens:
            break
        lines = candidate
    return _render(lines) if lines else None


def _render(lines: Sequence[str]) -> str:
    return MEMORIES_HEADER + "\n" + "\n".join(lines) + "]"
