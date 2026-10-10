"""What Mika remembers while the server runs: each user's recent turns (FIFO), the history window for the
prompt, and the archive behind them.

A user's recent turns are loaded from the archive the first time they speak, so Mika remembers the conversation
after a restart. Memory is a help, not a requirement: when the database fails, the turn goes on without it.
"""

import logging
from collections.abc import Sequence

from ..config import MemorySettings
from .archive import Archive, TurnRecord
from .cache import ConversationCache
from .turns import Turn

log = logging.getLogger(__name__)


class Conversation:
    def __init__(self, archive: Archive, settings: MemorySettings) -> None:
        self.archive = archive
        self._settings = settings
        self._cache = ConversationCache(settings.history_turns)
        self._loaded: set[str] = set()

    async def window(self, user_id: str) -> list[Turn]:
        """The recent turns for the user's next prompt, oldest first."""
        await self._load(user_id)
        return self._cache.window(user_id, self._settings.history_max_tokens)

    async def recall(self, message: str, history: Sequence[Turn]) -> list[str]:
        """Long-term memories similar to the message, except turns already in the history."""
        exclude = {turn.chat_log_id for turn in history if turn.chat_log_id is not None}
        try:
            return await self.archive.recall(message, exclude_chat_log_ids=exclude)
        except Exception:
            log.exception("Recalling memories failed; this turn goes on without them")
            return []

    async def record(self, record: TurnRecord) -> Turn | None:
        """Log the turn, and keep it as a recent turn if Mika said something."""
        try:
            chat_log_id = await self.archive.save(record)
        except Exception:
            log.exception("Saving the turn failed; it stays in the recent turns only")
            chat_log_id = None
        if not record.result.reply:
            return None
        turn = Turn(record.user_message, record.result, chat_log_id=chat_log_id)
        self._cache.add(record.user_id, turn)
        return turn

    async def _load(self, user_id: str) -> None:
        if user_id in self._loaded:
            return
        self._loaded.add(user_id)  # once per run, even if it fails: a broken database must not slow every turn
        try:
            turns = await self.archive.recent_turns(user_id, self._settings.history_turns)
        except Exception:
            log.exception("Loading %s's recent turns failed; starting without them", user_id)
            return
        self._cache.seed(user_id, [turn for turn in turns if turn.result.reply])
