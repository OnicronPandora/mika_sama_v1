import pytest
from psycopg import errors

from app.config import EMBEDDING_DIM
from app.db.schema import apply_schema
from mika_shared.enums import Emotion, FilterAction, Intent


async def fetch_all(conn, sql: str, params: tuple = ()) -> list[tuple]:
    cur = await conn.execute(sql, params)
    return await cur.fetchall()


async def test_creates_every_table(db):
    rows = await fetch_all(db, "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
    assert {name for (name,) in rows} == {"users", "chat_logs", "memory_embeddings", "personality_traits"}


async def test_can_run_again_on_an_existing_database(db):
    await apply_schema(db)


async def test_embedding_column_matches_the_config(db):
    rows = await fetch_all(
        db,
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = 'memory_embeddings'::regclass AND attname = 'embedding'",
    )
    assert rows == [(f"vector({EMBEDDING_DIM})",)]


async def test_indexes(db):
    rows = await fetch_all(db, "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()")
    indexes = dict(rows)
    assert "(user_id, created_at)" in indexes["chat_logs_user_created_idx"]
    assert "USING hnsw (embedding vector_cosine_ops)" in indexes["memory_embeddings_embedding_idx"]


INSERT = """
    INSERT INTO chat_logs (session_id, user_id, user_message, mika_intent, mika_emotion, mika_reply,
                           original_reply, filter_action)
    VALUES (gen_random_uuid(), 'admin', 'Hi', %(intent)s, %(emotion)s, 'Hi!', '[happy] Hi!', %(action)s)
"""
VALID = {"intent": "casual_conversation", "emotion": "happy", "action": "ALLOW"}


@pytest.mark.parametrize(
    ("column", "values"),
    [("intent", list(Intent)), ("emotion", list(Emotion)), ("action", list(FilterAction))],
)
async def test_check_constraints_accept_every_shared_enum_value(db, column, values):
    await db.execute("INSERT INTO users (user_id) VALUES ('admin')")
    for value in values:
        await db.execute(INSERT, {**VALID, column: value.value})


@pytest.mark.parametrize(("column", "value"), [("intent", "chitchat"), ("emotion", "HAPPY"), ("action", "allow")])
async def test_check_constraints_reject_other_values(db, column, value):
    await db.execute("INSERT INTO users (user_id) VALUES ('admin')")
    with pytest.raises(errors.CheckViolation):
        await db.execute(INSERT, {**VALID, column: value})
