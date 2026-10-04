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
from .turns import message_tokens

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


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


def memories_message(memories: Sequence[str], max_tokens: int) -> dict[str, str] | None:
    """Recalled memories as one system message, nearest first, within the budget. None if there are none."""
    header = "Things you remember from earlier conversations (they may be old):"
    message = {"role": "system", "content": header}
    for memory in memories:
        candidate = {"role": "system", "content": message["content"] + "\n- " + memory.replace("\n", " / ")}
        if message_tokens(candidate) > max_tokens:
            break
        message = candidate
    return message if message["content"] != header else None
