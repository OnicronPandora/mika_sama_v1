"""Recent turns per user, oldest dropped first (spec: FIFO message caching), and which of them go into the prompt."""

from collections import deque
from collections.abc import Iterable, Sequence

from .history import turn_tokens
from .turns import Turn


class ConversationCache:
    def __init__(self, max_turns: int) -> None:
        self._max_turns = max_turns
        self._turns: dict[str, deque[Turn]] = {}
        self._window_starts: dict[str, Turn] = {}  # the first turn of each user's history window

    def add(self, user_id: str, turn: Turn) -> None:
        self._turns.setdefault(user_id, deque(maxlen=self._max_turns)).append(turn)

    def seed(self, user_id: str, turns: Iterable[Turn]) -> None:
        """Fill the cache from the database, so Mika remembers the conversation after a restart."""
        self._turns[user_id] = deque(turns, maxlen=self._max_turns)

    def recent(self, user_id: str) -> list[Turn]:
        """Oldest first."""
        return list(self._turns.get(user_id, ()))

    def window(self, user_id: str, max_tokens: int) -> list[Turn]:
        """The recent turns that go into the prompt, oldest first, within max_tokens.

        The window keeps its first turn while new turns are added, so the prompt starts the same way from turn
        to turn and Ollama only reads what is new. When the window no longer fits, or its first turn has left
        the cache, it restarts with the newest turns that fit in half the budget, leaving room to grow.
        Asking again before a new turn is added gives the same window.
        """
        turns = self.recent(user_id)
        start = self._window_starts.get(user_id)
        for i, turn in enumerate(turns):
            if turn is start:
                if sum(turn_tokens(t) for t in turns[i:]) <= max_tokens:
                    return turns[i:]
                break
        kept = _newest_within(turns, max_tokens // 2) or _newest_within(turns, max_tokens)
        if kept:
            self._window_starts[user_id] = kept[0]
        else:
            self._window_starts.pop(user_id, None)
        return kept


def _newest_within(turns: Sequence[Turn], max_tokens: int) -> list[Turn]:
    """The newest turns whose messages fit in max_tokens, oldest first."""
    kept: list[Turn] = []
    used = 0
    for turn in reversed(turns):
        used += turn_tokens(turn)
        if used > max_tokens:
            break
        kept.append(turn)
    return kept[::-1]
