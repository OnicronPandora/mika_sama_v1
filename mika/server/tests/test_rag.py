import os
from uuid import uuid4

import numpy as np
import pytest

from app.config import EMBEDDING_DIM, MemorySettings
from app.db import queries
from app.memory.rag import DOCUMENT_PREFIX, QUERY_PREFIX, LocalEmbedder, MemoryStore
from mika_shared.enums import Emotion, FilterAction, Intent
from mika_shared.payloads import TurnResult

SETTINGS = MemorySettings(memory_count=2, memory_max_distance=0.5)


def axis(*weights: float) -> np.ndarray:
    vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    vector[: len(weights)] = weights
    return vector


class FakeEmbedder:
    """Deterministic embeddings: each known text maps to a fixed vector."""

    def __init__(self, vectors: dict[str, np.ndarray]) -> None:
        self.vectors = vectors
        self.calls: list[tuple[str, str]] = []

    async def embed_document(self, text: str) -> np.ndarray:
        self.calls.append(("document", text))
        return self.vectors[text]

    async def embed_query(self, text: str) -> np.ndarray:
        self.calls.append(("query", text))
        return self.vectors[text]


async def log_turn(db) -> int:
    await queries.touch_user(db, "admin")
    result = TurnResult(
        intent=Intent.CASUAL_CONVERSATION, emotion=Emotion.HAPPY, reply="Hi!", original_reply="[happy] Hi!",
        action=FilterAction.ALLOW,
    )
    return await queries.insert_chat_log(db, session_id=uuid4(), user_id="admin", user_message="Hi", result=result)


TURNS = {  # name: (user message, Mika's reply, embedding of the two without names)
    "cats": ("I adopted a cat.", "Cats are the best!", axis(1, 0, 0)),
    "games": ("I beat the boss.", "Ehehe~ nice!", axis(0, 1, 0)),
    "weather": ("It's raining.", "Cozy weather!", axis(0, 0, 1)),
}
VECTORS = {f"{user} {reply}": vector for user, reply, vector in TURNS.values()} | {
    "How is my cat?": axis(1, 0.2, 0),  # close to cats, a little to games
    "Tell me about the boss fight": axis(0.1, 1, 0),
}


def stored(name: str) -> str:
    user, reply, _ = TURNS[name]
    return f"Pandora: {user}\nMika-sama: {reply}"


async def remember_all(store: MemoryStore, db) -> dict[str, int]:
    ids = {}
    for name, (user, reply, _) in TURNS.items():
        ids[name] = await log_turn(db)
        await store.remember(db, chat_log_id=ids[name], speaker="Pandora", user_message=user, reply=reply)
    return ids


async def test_remember_and_recall(db):
    embedder = FakeEmbedder(VECTORS)
    store = MemoryStore(embedder, SETTINGS, assistant="Mika-sama")
    ids = await remember_all(store, db)
    # Only memories close enough are recalled: weather and games are too far from the cat question.
    assert await store.recall(db, "How is my cat?") == [stored("cats")]
    assert await store.recall(db, "Tell me about the boss fight") == [stored("games")]
    # Turns still in the recent history are not recalled again.
    assert await store.recall(db, "How is my cat?", exclude_chat_log_ids={ids["cats"]}) == []


async def test_memories_are_stored_with_names_but_embedded_without(db):
    embedder = FakeEmbedder(VECTORS)
    await remember_all(MemoryStore(embedder, SETTINGS, assistant="Mika-sama"), db)
    assert ("document", "I adopted a cat. Cats are the best!") in embedder.calls
    cur = await db.execute("SELECT content FROM memory_embeddings ORDER BY id LIMIT 1")
    assert await cur.fetchone() == (stored("cats"),)


async def test_recall_returns_at_most_memory_count(db):
    vectors = {"a x": axis(1, 0), "b x": axis(1, 0.01), "c x": axis(1, 0.02), "q": axis(1, 0)}
    store = MemoryStore(FakeEmbedder(vectors), SETTINGS, assistant="Mika-sama")
    for user in ("a", "b", "c"):
        await store.remember(db, chat_log_id=await log_turn(db), speaker="Pandora", user_message=user, reply="x")
    assert await store.recall(db, "q") == ["Pandora: a\nMika-sama: x", "Pandora: b\nMika-sama: x"]


async def test_local_embedder_adds_nomic_task_prefixes():
    seen: list[str] = []

    class FakeModel:
        def embed(self, texts):
            seen.extend(texts)
            yield axis(1)

    embedder = LocalEmbedder(MemorySettings())
    embedder._model = FakeModel()
    await embedder.embed_document("a memory")
    await embedder.embed_query("a question")
    assert seen == [DOCUMENT_PREFIX + "a memory", QUERY_PREFIX + "a question"]


@pytest.mark.skipif(not os.environ.get("MIKA_TEST_EMBEDDINGS"), reason="set MIKA_TEST_EMBEDDINGS=1 (downloads 0.13 GB once)")
async def test_the_real_model_ranks_by_meaning():
    embedder = LocalEmbedder(MemorySettings())
    cat = await embedder.embed_document("Pandora: I adopted a kitten named Mochi.\nMika-sama: Mochi is adorable!")
    rain = await embedder.embed_document("Pandora: It's raining all week.\nMika-sama: Perfect weather for games.")
    query = await embedder.embed_query("How is your cat doing?")

    def cosine(a, b):
        return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))

    assert cat.shape == (EMBEDDING_DIM,)
    assert cosine(query, cat) > cosine(query, rain)
