"""One remembered exchange, and the token estimate the prompt budgets use."""

from dataclasses import dataclass

from mika_shared.payloads import TurnResult

from ..db.queries import ChatLog

# Measured on the Mac: Mika's prompt is about 4.2 characters per token, chat formatting included.
CHARS_PER_TOKEN = 4
MESSAGE_OVERHEAD = 5  # role header tokens per chat message


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


def message_tokens(message: dict[str, str]) -> int:
    return estimate_tokens(message["content"]) + MESSAGE_OVERHEAD


@dataclass(frozen=True)
class Turn:
    """What a user said and what came of it (the spec's response payload)."""

    user_message: str
    result: TurnResult
    chat_log_id: int | None = None  # set once the turn is logged

    @classmethod
    def from_chat_log(cls, log: ChatLog) -> "Turn":
        return cls(user_message=log.user_message, result=log.result, chat_log_id=log.id)
