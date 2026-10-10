"""Recent turns as chat messages for the LLM, and as plain text for the output filter.

Decision #2: the prompt context uses both reply and original_reply. A filtered turn shows what Mika
actually said, followed by a note with what she originally wrote and what the filter did.

The note is a user message, not a system message: Ollama moves every system message to the top of the prompt
(llama3.1's chat template), away from the turn it is about. Consecutive messages with the same role are
joined (merge_roles), so the note becomes the start of the next user message.
"""

from collections.abc import Sequence

from mika_shared.enums import FilterAction

from ..llm.tag_parser import EmotionTagParser
from .turns import Turn, message_tokens


def strip_tag(text: str) -> str:
    parser = EmotionTagParser()
    return (parser.feed(text) + parser.finish()).strip()


def filter_note(turn: Turn) -> str | None:
    result = turn.result
    if result.action is FilterAction.ALLOW:
        return None
    return (
        f"[Note: the stream's filter changed your last reply ({result.action.value}). "
        f"What you originally wrote: {strip_tag(result.original_reply)}]"
    )


def turn_messages(turn: Turn) -> list[dict[str, str]]:
    result = turn.result
    # The tag is kept on Mika's past replies: seeing the format again helps the model keep using it.
    messages = [
        {"role": "user", "content": turn.user_message},
        {"role": "assistant", "content": f"[{result.emotion.value}] {result.reply}"},
    ]
    if note := filter_note(turn):
        messages.append({"role": "user", "content": note})
    return messages


def turn_tokens(turn: Turn) -> int:
    return sum(message_tokens(message) for message in turn_messages(turn))


def history_messages(turns: Sequence[Turn]) -> list[dict[str, str]]:
    """The turns as chat messages, oldest first (ConversationCache.window picks which turns fit)."""
    return [message for turn in turns for message in turn_messages(turn)]


def merge_roles(messages: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Join consecutive messages with the same role, as Ollama does before applying the chat template.

    The messages sent are then exactly what the model reads, which keeps prompts comparable from call to call.
    """
    merged: list[dict[str, str]] = []
    for message in messages:
        if merged and merged[-1]["role"] == message["role"]:
            merged[-1] = {"role": message["role"], "content": merged[-1]["content"] + "\n\n" + message["content"]}
        else:
            merged.append(dict(message))
    return merged


def history_text(turns: Sequence[Turn], *, speaker: str, assistant: str, max_turns: int) -> str:
    """The last few turns as plain text: what was actually said, for the output filter's context."""
    if max_turns <= 0:
        return ""
    lines = []
    for turn in turns[-max_turns:]:
        lines += [f"{speaker}: {turn.user_message}", f"{assistant}: {turn.result.reply}"]
    return "\n".join(lines)
