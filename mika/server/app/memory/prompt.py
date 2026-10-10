"""The messages for one turn (spec: personality YAML + learned traits + FIFO history + RAG context + message).

    system prompt -> recent turns -> one user message: [filter note] + [memories] + the message

What changes least comes first, so Ollama can reuse what it has already read: the system prompt never changes,
and the history window only grows until it restarts (ConversationCache.window). Between turns the server warms
Ollama up with prefix_messages(), so the next turn only reads its memories and message.

The system prompt is the only system message: Ollama moves every system message to the top of the prompt, so
memories and filter notes go into the user's message instead. The prompt plus the reply must fit the model's
4096-token context.
"""

from .history import merge_roles
from .turns import CHARS_PER_TOKEN, MESSAGE_OVERHEAD, message_tokens

CONTEXT_TOKENS = 4096
SAFETY_MARGIN = 100  # the token estimate is approximate


def prefix_messages(*, system_prompt: str, history: list[dict[str, str]]) -> list[dict[str, str]]:
    """What the user's next prompt starts with: the system prompt and the history (with a trailing filter note,
    if the last turn was filtered)."""
    return merge_roles([{"role": "system", "content": system_prompt}, *history])


def build_turn_messages(
    *,
    system_prompt: str,
    history: list[dict[str, str]],
    memories: str | None,
    user_message: str,
    num_predict: int,
) -> list[dict[str, str]]:
    limit = CONTEXT_TOKENS - num_predict - SAFETY_MARGIN
    system = {"role": "system", "content": system_prompt}
    # The history and memory budgets keep a normal turn far below the limit. Only an unusually long message
    # can overflow it: then drop the history, then the memories, then shorten the message itself.
    for kept_history, kept_memories in ((history, memories), ([], memories), ([], None)):
        content = "\n\n".join(part for part in (kept_memories, user_message) if part)
        messages = merge_roles([system, *kept_history, {"role": "user", "content": content}])
        if sum(message_tokens(message) for message in messages) <= limit:
            return messages
    room = (limit - message_tokens(system) - MESSAGE_OVERHEAD) * CHARS_PER_TOKEN
    return [system, {"role": "user", "content": user_message[: max(room, 0)]}]
