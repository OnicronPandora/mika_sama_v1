"""What the output filter knows about the turn while it checks a sentence."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnContext:
    user_message: str
    history: str = ""  # recent turns, already formatted (memory, Phase 5)
    reply_so_far: str = ""  # what Mika has actually said so far in this reply, after filtering
