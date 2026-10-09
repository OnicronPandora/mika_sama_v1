"""The messages for one turn (spec: personality YAML + learned traits + FIFO history + RAG context + message).

Order: system prompt, recent turns, recalled memories, the user's message. What changes least comes first,
so Ollama can reuse it when its cache allows; the memories change every turn, so they sit just before the
message. The prompt plus the reply must fit the model's 4096-token context.
"""

from .turns import CHARS_PER_TOKEN, MESSAGE_OVERHEAD, message_tokens

CONTEXT_TOKENS = 4096
SAFETY_MARGIN = 100  # the token estimate is approximate


def build_turn_messages(
    *,
    system_prompt: str,
    history: list[dict[str, str]],
    memories: dict[str, str] | None,
    user_message: str,
    num_predict: int,
) -> list[dict[str, str]]:
    limit = CONTEXT_TOKENS - num_predict - SAFETY_MARGIN
    system = {"role": "system", "content": system_prompt}
    user = {"role": "user", "content": user_message}
    recalled = [memories] if memories else []
    # The history and memory budgets keep a normal turn far below the limit. Only an unusually long message
    # can overflow it: then drop the history, then the memories, then shorten the message itself.
    for kept_history, kept_memories in ((history, recalled), ([], recalled), ([], [])):
        messages = [system, *kept_history, *kept_memories, user]
        if sum(message_tokens(message) for message in messages) <= limit:
            return messages
    room = (limit - message_tokens(system) - MESSAGE_OVERHEAD) * CHARS_PER_TOKEN
    return [system, {"role": "user", "content": user_message[: max(room, 0)]}]
