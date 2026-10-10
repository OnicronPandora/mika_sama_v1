"""Test doubles: the LLM engine, the embedder, and the server's services running on them."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import numpy as np

from app.config import EMBEDDING_DIM, DatabaseSettings, FilterSettings, LLMSettings, ServerSettings, Settings
from app.filter.ai_classifier import load_filter_policy
from app.memory.archive import MemoryArchive
from app.personality.engine import load_personality
from app.services import Services, build_services
from mika_shared.payloads import ADMIN_USER_ID

HANG = object()  # in a scripted reply: stop here and wait until cancelled


@dataclass
class Call:
    messages: list[dict[str, str]]
    temperature: float
    num_predict: int
    json_schema: dict | None
    label: str = "complete"


class FakeEngine:
    """Scripted LLM.

    complete() answers come from `answers`, in order: a string to return, an exception to raise, or a number of
    seconds to hang (to trigger a timeout). stream_chat() replies come from `replies`, in order: a list of tokens
    (an exception or HANG in the list raises or waits there), or an exception raised at once.
    """

    def __init__(self, *answers, replies=()) -> None:
        self.answers = list(answers)
        self.replies = list(replies)
        self.calls: list[Call] = []
        self.streams: list[list[dict[str, str]]] = []  # the messages of each stream_chat call
        self.warm_ups: list[list[dict[str, str]]] = []
        self.open_streams = 0  # replies started and not yet closed

    async def complete(self, messages, *, temperature, num_predict, json_schema=None, label="complete") -> str:
        self.calls.append(Call(list(messages), temperature, num_predict, json_schema, label))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, (int, float)):
            await asyncio.sleep(answer)
            return ""
        return answer

    async def stream_chat(self, messages, *, on_stats=None, label="reply"):
        self.streams.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        self.open_streams += 1
        try:
            for token in reply:
                if token is HANG:
                    await asyncio.Event().wait()
                if isinstance(token, BaseException):
                    raise token
                yield token
        finally:
            self.open_streams -= 1

    async def warm_up(self, messages, *, label="warm-up") -> None:
        self.warm_ups.append(list(messages))

    async def close(self) -> None:
        pass

    @property
    def classifier_calls(self) -> list[Call]:
        return [call for call in self.calls if call.json_schema]

    @property
    def replacer_calls(self) -> list[Call]:
        return [call for call in self.calls if not call.json_schema]


def verdict(safe: bool, reason: str = "test") -> str:
    """A classifier answer as Ollama returns it."""
    return json.dumps({"safe": safe, "reason": reason})


class FakeEmbedder:
    """The same vector for every text: enough for tests that store and recall memories without ranking them."""

    async def embed_document(self, text: str) -> np.ndarray:
        return self._vector()

    async def embed_query(self, text: str) -> np.ndarray:
        return self._vector()

    @staticmethod
    def _vector() -> np.ndarray:
        vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        vector[0] = 1
        return vector


def is_prompt_prefix(prefix: list[dict], messages: list[dict]) -> bool:
    """Whether a prompt made of `messages` starts with the text of `prefix` once the chat template renders it
    (so Ollama can reuse what it read for `prefix`)."""
    *head, last = prefix
    nxt = messages[len(head)]
    return messages[: len(head)] == head and nxt["role"] == last["role"] and nxt["content"].startswith(last["content"])


def fake_settings(*, mode: str = "separate", reply_timeout: float = 60.0, **server) -> Settings:
    """Settings for a server without a database; fast filter timeouts."""
    return Settings(
        db=DatabaseSettings(name="unused", user="unused", password="unused"),
        llm=LLMSettings(reply_timeout=reply_timeout),
        filter=FilterSettings(classifier_timeout=1, replacer_timeout=1, context_mode=mode),
        server=ServerSettings(**server),
    )


@asynccontextmanager
async def open_fake_services(
    settings: Settings, engine: FakeEngine, archive: MemoryArchive | None = None
) -> AsyncIterator[Services]:
    """The server's services on a scripted LLM and an in-memory archive (no database, no Ollama)."""
    services = build_services(
        settings,
        engine=engine,
        archive=archive or MemoryArchive(),
        personality=load_personality(),
        policy=load_filter_policy(),
    )
    await engine.warm_up(await services.runner.prefix(ADMIN_USER_ID), label="startup")
    yield services
