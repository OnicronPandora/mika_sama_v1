"""Where turns are kept for good: chat_logs and the long-term memories (PostgreSQL + pgvector).

PgArchive is the server's. MemoryArchive keeps turns in memory only, for the tests and for app.turn.bench,
which must not write to Mika's real database.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from mika_shared.payloads import TurnResult

from ..db import queries
from .rag import MemoryStore
from .turns import Turn


@dataclass(frozen=True)
class TurnRecord:
    """One finished turn, as it is logged."""

    session_id: UUID
    user_id: str
    speaker: str  # how the user is named in memories ("Pandora" for the admin)
    user_message: str
    result: TurnResult
    rag_context_used: str | None = None
    filter_reason: str | None = None


class Archive(Protocol):
    async def recent_turns(self, user_id: str, limit: int) -> list[Turn]: ...

    async def recall(self, query: str, *, exclude_chat_log_ids: Collection[int] = ()) -> list[str]: ...

    async def save(self, record: TurnRecord) -> int: ...


class PgArchive:
    def __init__(self, pool: AsyncConnectionPool, memories: MemoryStore, *, timeout: float = 10) -> None:
        self._pool = pool
        self._memories = memories
        self._timeout = timeout  # longest wait for a free connection

    async def recent_turns(self, user_id: str, limit: int) -> list[Turn]:
        """The user's last turns, oldest first."""
        async with self._pool.connection(timeout=self._timeout) as conn:
            logs = await queries.recent_chat_logs(conn, user_id, limit)
        return [Turn.from_chat_log(log) for log in logs]

    async def recall(self, query: str, *, exclude_chat_log_ids: Collection[int] = ()) -> list[str]:
        async with self._pool.connection(timeout=self._timeout) as conn:
            return await self._memories.recall(conn, query, exclude_chat_log_ids=exclude_chat_log_ids)

    async def save(self, record: TurnRecord) -> int:
        """Log the turn (and the user) in one transaction. It becomes a memory if Mika said something."""
        async with self._pool.connection(timeout=self._timeout) as conn:
            await queries.touch_user(conn, record.user_id, username=record.speaker)
            chat_log_id = await queries.insert_chat_log(
                conn,
                session_id=record.session_id,
                user_id=record.user_id,
                user_message=record.user_message,
                result=record.result,
                rag_context_used=record.rag_context_used,
                filter_reason=record.filter_reason,
            )
            if record.result.reply:
                await self._memories.remember(
                    conn,
                    chat_log_id=chat_log_id,
                    speaker=record.speaker,
                    user_message=record.user_message,
                    reply=record.result.reply,
                )
        return chat_log_id


class MemoryArchive:
    """Turns in a list; memories come from the recall function, if any (by default nothing is recalled)."""

    def __init__(self, recall: Callable[[str], list[str]] | None = None) -> None:
        self.records: list[TurnRecord] = []
        self._recall = recall

    async def recent_turns(self, user_id: str, limit: int) -> list[Turn]:
        turns = [
            Turn(record.user_message, record.result, chat_log_id=i)
            for i, record in enumerate(self.records, start=1)
            if record.user_id == user_id
        ]
        return turns[-limit:] if limit > 0 else []

    async def recall(self, query: str, *, exclude_chat_log_ids: Collection[int] = ()) -> list[str]:
        return self._recall(query) if self._recall else []

    async def save(self, record: TurnRecord) -> int:
        self.records.append(record)
        return len(self.records)
