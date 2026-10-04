from datetime import datetime
from uuid import uuid4

import numpy as np
import pytest
from psycopg import errors

from app.config import EMBEDDING_DIM
from app.db import queries
from mika_shared.enums import Emotion, FilterAction, Intent
from mika_shared.payloads import TurnResult

SESSION = uuid4()
RESULT = TurnResult(
    intent=Intent.FILTER_INCIDENT,
    emotion=Emotion.CONFUSED,
    reply="Filtered. Let's talk about something else!",
    original_reply="[confused] Something unsafe.",
    action=FilterAction.REPLACE,
)


def axis(index: int) -> np.ndarray:
    """A unit vector along one axis: cosine distance 0 to itself and 1 to any other axis."""
    vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    vector[index] = 1.0
    return vector


async def log_turn(db, user_id: str = "admin") -> int:
    await queries.touch_user(db, user_id)
    return await queries.insert_chat_log(
        db,
        session_id=SESSION,
        user_id=user_id,
        user_message="Hi Mika!",
        result=RESULT,
        rag_context_used="(no memories)",
        filter_reason="classifier: unsafe",
    )


async def test_chat_log_round_trip(db):
    log = await queries.get_chat_log(db, await log_turn(db))
    assert log is not None
    assert log.result == RESULT
    assert (log.session_id, log.user_id, log.user_message) == (SESSION, "admin", "Hi Mika!")
    assert (log.rag_context_used, log.filter_reason) == ("(no memories)", "classifier: unsafe")
    assert isinstance(log.created_at, datetime)


async def test_unknown_chat_log(db):
    assert await queries.get_chat_log(db, 12345) is None


async def test_chat_log_needs_a_known_user(db):
    with pytest.raises(errors.ForeignKeyViolation):
        await queries.insert_chat_log(db, session_id=SESSION, user_id="nobody", user_message="Hi", result=RESULT)


async def test_touch_user_counts_interactions(db):
    await queries.touch_user(db, "admin", username="Admin", platform="local")
    await queries.touch_user(db, "admin")  # later calls keep the known username and platform
    cur = await db.execute(
        "SELECT username, platform, interaction_count, last_seen >= created_at FROM users WHERE user_id = 'admin'"
    )
    assert await cur.fetchone() == ("Admin", "local", 2, True)


async def test_nearest_memories(db):
    log_id = await log_turn(db)
    for index in range(3):
        await queries.insert_memory(db, chat_log_id=log_id, content=f"memory {index}", embedding=axis(index))
    query = axis(1) + 0.1 * axis(2)  # closest to memory 1, then memory 2, then memory 0
    matches = await queries.nearest_memories(db, query, limit=2)
    assert [m.content for m in matches] == ["memory 1", "memory 2"]
    assert matches[0].distance < matches[1].distance
    assert all(m.chat_log_id == log_id for m in matches)


async def test_embedding_size_is_checked(db):
    log_id = await log_turn(db)
    with pytest.raises(ValueError):
        await queries.insert_memory(db, chat_log_id=log_id, content="x", embedding=[0.1, 0.2])
    with pytest.raises(ValueError):
        await queries.nearest_memories(db, np.zeros(EMBEDDING_DIM + 1))
    with pytest.raises(ValueError):
        await queries.nearest_memories(db, axis(0), limit=0)


async def test_recent_chat_logs_oldest_first(db):
    ids = [await log_turn(db) for _ in range(4)]
    await log_turn(db, user_id="someone else")
    logs = await queries.recent_chat_logs(db, "admin", limit=3)
    assert [log.id for log in logs] == ids[1:]
    assert all(log.user_id == "admin" for log in logs)


async def test_active_traits_oldest_first(db):
    await db.execute("INSERT INTO personality_traits (trait) VALUES ('Loves rainy days')")
    await db.execute("INSERT INTO personality_traits (trait, active) VALUES ('An old habit', false)")
    await db.execute("INSERT INTO personality_traits (trait) VALUES ('Hates spiders')")
    assert await queries.active_traits(db) == ["Loves rainy days", "Hates spiders"]


async def test_deleting_a_chat_log_deletes_its_memories(db):
    log_id = await log_turn(db)
    await queries.insert_memory(db, chat_log_id=log_id, content="x", embedding=axis(0))
    await db.execute("DELETE FROM chat_logs WHERE id = %s", (log_id,))
    assert await queries.nearest_memories(db, axis(0)) == []
