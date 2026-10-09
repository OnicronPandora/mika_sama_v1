"""Queries for the tables in scripts/setup_db.sql.

Vector queries need a connection with the pgvector adapter registered (every pool connection has it).
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import numpy as np
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict

from mika_shared.enums import Emotion, FilterAction, Intent
from mika_shared.payloads import TurnResult

from ..config import EMBEDDING_DIM


class ChatLog(BaseModel):
    """One row of chat_logs."""

    model_config = ConfigDict(frozen=True)

    id: int
    session_id: UUID
    user_id: str
    user_message: str
    rag_context_used: str | None
    mika_intent: Intent
    mika_emotion: Emotion
    mika_reply: str
    original_reply: str
    filter_action: FilterAction
    filter_reason: str | None
    created_at: datetime

    @property
    def result(self) -> TurnResult:
        return TurnResult(
            intent=self.mika_intent,
            emotion=self.mika_emotion,
            reply=self.mika_reply,
            original_reply=self.original_reply,
            action=self.filter_action,
        )


class MemoryMatch(BaseModel):
    """A stored memory and its cosine distance to the query (0 = same direction, 2 = opposite)."""

    model_config = ConfigDict(frozen=True)

    id: int
    chat_log_id: int
    content: str
    distance: float


async def touch_user(
    conn: AsyncConnection, user_id: str, *, username: str | None = None, platform: str | None = None
) -> None:
    """Create the user on first contact; after that, count the interaction and update last_seen."""
    await conn.execute(
        """
        INSERT INTO users (user_id, username, platform, interaction_count)
        VALUES (%(user_id)s, %(username)s, %(platform)s, 1)
        ON CONFLICT (user_id) DO UPDATE SET
            interaction_count = users.interaction_count + 1,
            last_seen = now(),
            username = COALESCE(EXCLUDED.username, users.username),
            platform = COALESCE(EXCLUDED.platform, users.platform)
        """,
        {"user_id": user_id, "username": username, "platform": platform},
    )


async def insert_chat_log(
    conn: AsyncConnection,
    *,
    session_id: UUID,
    user_id: str,
    user_message: str,
    result: TurnResult,
    rag_context_used: str | None = None,
    filter_reason: str | None = None,
) -> int:
    """Log one turn and return its id. The user must already exist (touch_user)."""
    cur = await conn.execute(
        """
        INSERT INTO chat_logs (session_id, user_id, user_message, rag_context_used, mika_intent, mika_emotion,
                               mika_reply, original_reply, filter_action, filter_reason)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            session_id,
            user_id,
            user_message,
            rag_context_used,
            result.intent.value,
            result.emotion.value,
            result.reply,
            result.original_reply,
            result.action.value,
            filter_reason,
        ),
    )
    row = await cur.fetchone()
    return row[0]


async def get_chat_log(conn: AsyncConnection, chat_log_id: int) -> ChatLog | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM chat_logs WHERE id = %s", (chat_log_id,))
        row = await cur.fetchone()
    return ChatLog.model_validate(row) if row else None


async def recent_chat_logs(conn: AsyncConnection, user_id: str, limit: int) -> list[ChatLog]:
    """The user's last turns, oldest first (to refill the FIFO cache when the server starts)."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT * FROM (
                SELECT * FROM chat_logs WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT %s
            ) AS recent
            ORDER BY created_at, id
            """,
            (user_id, limit),
        )
        return [ChatLog.model_validate(row) for row in await cur.fetchall()]


async def insert_memory(
    conn: AsyncConnection, *, chat_log_id: int, content: str, embedding: Sequence[float] | np.ndarray
) -> int:
    """Store the embedding of one turn's text and return the memory's id."""
    cur = await conn.execute(
        "INSERT INTO memory_embeddings (chat_log_id, content, embedding) VALUES (%s, %s, %s) RETURNING id",
        (chat_log_id, content, _as_vector(embedding)),
    )
    row = await cur.fetchone()
    return row[0]


async def nearest_memories(
    conn: AsyncConnection, embedding: Sequence[float] | np.ndarray, *, limit: int = 5
) -> list[MemoryMatch]:
    """The stored memories closest to the embedding by cosine distance, nearest first."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT id, chat_log_id, content, embedding <=> %(query)s AS distance
            FROM memory_embeddings
            ORDER BY embedding <=> %(query)s
            LIMIT %(limit)s
            """,
            {"query": _as_vector(embedding), "limit": limit},
        )
        return [MemoryMatch.model_validate(row) for row in await cur.fetchall()]


async def active_traits(conn: AsyncConnection) -> list[str]:
    """The traits Mika has learned and still holds, oldest first (the second personality layer)."""
    cur = await conn.execute("SELECT trait FROM personality_traits WHERE active ORDER BY created_at, id")
    return [trait for (trait,) in await cur.fetchall()]


def _as_vector(embedding: Sequence[float] | np.ndarray) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32)
    if vector.shape != (EMBEDDING_DIM,):
        raise ValueError(f"expected an embedding of {EMBEDDING_DIM} numbers, got shape {vector.shape}")
    return vector
