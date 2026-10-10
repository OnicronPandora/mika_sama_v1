from uuid import uuid4

from fakes import FakeEmbedder

from app.config import MemorySettings
from app.db.pool import open_pool
from app.memory.archive import MemoryArchive, PgArchive, TurnRecord
from app.memory.conversation import Conversation
from app.memory.rag import MemoryStore
from app.memory.turns import Turn
from mika_shared.enums import Emotion, FilterAction, Intent
from mika_shared.payloads import TurnResult

SESSION = uuid4()


def result(reply: str, intent: Intent = Intent.CASUAL_CONVERSATION) -> TurnResult:
    return TurnResult(
        intent=intent, emotion=Emotion.HAPPY, reply=reply, original_reply=f"[happy] {reply}", action=FilterAction.ALLOW
    )


def record(message: str, reply: str, user_id: str = "admin", **fields) -> TurnRecord:
    return TurnRecord(
        session_id=SESSION, user_id=user_id, speaker="Pandora", user_message=message, result=result(reply), **fields
    )


async def test_recent_turns_are_loaded_from_the_archive_once():
    archive = MemoryArchive()
    for i in range(3):
        await archive.save(record(f"Message {i}", f"Reply {i}."))
    await archive.save(record("Hello?", ""))  # a failed turn: logged, but not part of the conversation
    await archive.save(record("Hi!", "Hi, stranger.", user_id="someone"))
    conversation = Conversation(archive, MemorySettings(history_turns=6))
    window = await conversation.window("admin")
    assert [turn.user_message for turn in window] == ["Message 0", "Message 1", "Message 2"]
    assert [turn.chat_log_id for turn in window] == [1, 2, 3]
    archive.records.clear()
    assert await conversation.window("admin") == window  # not loaded again


async def test_recall_skips_turns_already_in_the_history():
    seen = []

    class RecordingArchive(MemoryArchive):
        async def recall(self, query, *, exclude_chat_log_ids=()):
            seen.append((query, set(exclude_chat_log_ids)))
            return ["a memory"]

    conversation = Conversation(RecordingArchive(), MemorySettings())
    history = [Turn("Hi", result("Hi!"), chat_log_id=7), Turn("Yo", result("Yo!"))]  # the second wasn't logged
    assert await conversation.recall("How are you?", history) == ["a memory"]
    assert seen == [("How are you?", {7})]


async def test_recording_keeps_turns_with_a_reply():
    conversation = Conversation(MemoryArchive(), MemorySettings())
    turn = await conversation.record(record("Hi", "Hi!"))
    assert turn == Turn("Hi", result("Hi!"), chat_log_id=1)
    assert await conversation.record(record("Hello?", "")) is None
    assert await conversation.window("admin") == [turn]


class BrokenArchive:
    async def recent_turns(self, user_id, limit):
        raise ConnectionError("database down")

    async def recall(self, query, *, exclude_chat_log_ids=()):
        raise ConnectionError("database down")

    async def save(self, record):
        raise ConnectionError("database down")


async def test_a_broken_database_doesnt_stop_the_conversation(caplog):
    conversation = Conversation(BrokenArchive(), MemorySettings())
    assert await conversation.window("admin") == []
    assert await conversation.recall("Hi", []) == []
    turn = await conversation.record(record("Hi", "Hi!"))
    assert turn == Turn("Hi", result("Hi!"), chat_log_id=None)  # kept in memory, not in the database
    assert await conversation.window("admin") == [turn]
    assert "Saving the turn failed" in caplog.text


async def test_postgres_archive(schema_db, db):
    settings = MemorySettings(memory_count=2)
    pool = await open_pool(schema_db)
    try:
        archive = PgArchive(pool, MemoryStore(FakeEmbedder(), settings, assistant="Mika-sama"))
        first = await archive.save(record("I adopted a cat.", "Cats are the best!", rag_context_used="[memories]"))
        failed = await archive.save(record("Hello?", "", filter_reason="classifier: test"))
        assert await archive.recent_turns("admin", 5) == [
            Turn("I adopted a cat.", result("Cats are the best!"), chat_log_id=first),
            Turn("Hello?", result(""), chat_log_id=failed),
        ]
        # Only the turn where Mika said something became a memory.
        assert await archive.recall("How is my cat?") == ["Pandora: I adopted a cat.\nMika-sama: Cats are the best!"]
        assert await archive.recall("How is my cat?", exclude_chat_log_ids={first}) == []
    finally:
        await pool.close()
    cur = await db.execute("SELECT user_id, username, interaction_count FROM users")
    assert await cur.fetchall() == [("admin", "Pandora", 2)]
    cur = await db.execute("SELECT rag_context_used, filter_reason FROM chat_logs ORDER BY id")
    assert await cur.fetchall() == [("[memories]", None), (None, "classifier: test")]
