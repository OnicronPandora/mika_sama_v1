"""Recent turns as chat messages for the LLM, and as plain text for the output filter.

Decision #2: the prompt context uses both reply and original_reply. A filtered turn shows what Mika
actually said, followed by a system note with what she originally wrote and what the filter did.
"""

from collections.abc import Sequence

from mika_shared.enums import FilterAction

from ..llm.tag_parser import EmotionTagParser
from .turns import Turn, message_tokens


def strip_tag(text: str) -> str:
    parser = EmotionTagParser()
    return (parser.feed(text) + parser.finish()).strip()


def turn_messages(turn: Turn) -> list[dict[str, str]]:
    result = turn.result
    # The tag is kept on Mika's past replies: seeing the format again helps the model keep using it.
    messages = [
        {"role": "user", "content": turn.user_message},
        {"role": "assistant", "content": f"[{result.emotion.value}] {result.reply}"},
    ]
    if result.action is not FilterAction.ALLOW:
        messages.append(
            {
                "role": "system",
                "content": f"Note: the stream's filter changed your reply above ({result.action.value}). "
                f"What you originally wrote: {strip_tag(result.original_reply)}",
            }
        )
    return messages


def history_messages(turns: Sequence[Turn], max_tokens: int) -> list[dict[str, str]]:
    """The most recent turns that fit the budget, oldest first. Whole turns are dropped, oldest first."""
    kept: list[list[dict[str, str]]] = []
    used = 0
    for turn in reversed(turns):
        messages = turn_messages(turn)
        cost = sum(message_tokens(message) for message in messages)
        if used + cost > max_tokens:
            break
        kept.append(messages)
        used += cost
    return [message for messages in reversed(kept) for message in messages]


def history_text(turns: Sequence[Turn], *, speaker: str, assistant: str, max_turns: int) -> str:
    """The last few turns as plain text: what was actually said, for the output filter's context."""
    if max_turns <= 0:
        return ""
    lines = []
    for turn in turns[-max_turns:]:
        lines += [f"{speaker}: {turn.user_message}", f"{assistant}: {turn.result.reply}"]
    return "\n".join(lines)
