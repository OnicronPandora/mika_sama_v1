"""Recent turns per user, oldest dropped first (spec: FIFO message caching)."""

from collections import deque
from collections.abc import Iterable

from .turns import Turn


class ConversationCache:
    def __init__(self, max_turns: int) -> None:
        self._max_turns = max_turns
        self._turns: dict[str, deque[Turn]] = {}

    def add(self, user_id: str, turn: Turn) -> None:
        self._turns.setdefault(user_id, deque(maxlen=self._max_turns)).append(turn)

    def seed(self, user_id: str, turns: Iterable[Turn]) -> None:
        """Fill the cache from the database at startup, so Mika remembers the conversation after a restart."""
        self._turns[user_id] = deque(turns, maxlen=self._max_turns)

    def recent(self, user_id: str) -> list[Turn]:
        """Oldest first."""
        return list(self._turns.get(user_id, ()))
