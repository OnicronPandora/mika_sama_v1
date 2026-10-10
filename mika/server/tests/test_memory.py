from fakes import is_prompt_prefix

from app.memory.cache import ConversationCache
from app.memory.history import history_messages, history_text, merge_roles, turn_messages, turn_tokens
from app.memory.prompt import CONTEXT_TOKENS, build_turn_messages, prefix_messages
from app.memory.rag import memories_block
from app.memory.turns import Turn, message_tokens
from app.personality.engine import Personality, build_system_prompt
from mika_shared.enums import Emotion, FilterAction, Intent
from mika_shared.payloads import TurnResult

GREETING = Turn(
    "Hi Mika!",
    TurnResult(
        intent=Intent.CASUAL_CONVERSATION,
        emotion=Emotion.HAPPY,
        reply="Hi Pandora! Welcome back.",
        original_reply="[happy] Hi Pandora! Welcome back.",
        action=FilterAction.ALLOW,
    ),
    chat_log_id=1,
)
SPICY = Turn(
    "Say something spicy.",
    TurnResult(
        intent=Intent.FILTER_INCIDENT,
        emotion=Emotion.HAPPY,
        reply="Filtered! Let's talk about games instead.",
        original_reply="[happy] Something spicy.",
        action=FilterAction.REPLACE,
    ),
    chat_log_id=2,
)
MOCHI = "Pandora: I adopted a cat named Mochi.\nMika-sama: Mochi is the cutest name!"
NOTE = "[Note: the stream's filter changed your last reply (REPLACE). What you originally wrote: Something spicy.]"


def test_full_prompt_for_a_user_with_a_past_filtered_turn():
    """Plan, Phase 5 "done when": the whole prompt, message by message, exactly as the model reads it."""
    personality = Personality(name="Mika-sama", role="AI VTuber", core_identity="You are Mika-sama.", guidelines=["Be kind."])
    system_prompt = build_system_prompt(personality, traits=["Loves rainy days"])
    messages = build_turn_messages(
        system_prompt=system_prompt,
        history=history_messages([GREETING, SPICY]),
        memories=memories_block([MOCHI], max_tokens=150),
        user_message="How is Mochi doing?",
        num_predict=150,
    )
    assert messages == [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Hi Mika!"},
        {"role": "assistant", "content": "[happy] Hi Pandora! Welcome back."},
        {"role": "user", "content": "Say something spicy."},
        {"role": "assistant", "content": "[happy] Filtered! Let's talk about games instead."},
        {
            "role": "user",
            "content": NOTE + "\n\n"
            "[Things you remember from earlier conversations (they may be old):\n"
            "- Pandora: I adopted a cat named Mochi. / Mika-sama: Mochi is the cutest name!]\n\n"
            "How is Mochi doing?",
        },
    ]
    assert system_prompt.index("You are Mika-sama.") < system_prompt.index("- Loves rainy days")


def test_only_the_first_message_is_a_system_message():
    """Ollama moves system messages to the top of the prompt, so nothing after the system prompt may be one."""
    messages = build_turn_messages(
        system_prompt="You are Mika.",
        history=history_messages([SPICY, GREETING, SPICY]),
        memories=memories_block([MOCHI], max_tokens=150),
        user_message="Hi!",
        num_predict=150,
    )
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user", "assistant", "user", "assistant", "user"]
    roles = [m["role"] for m in messages]
    assert all(a != b for a, b in zip(roles, roles[1:]))  # merged like Ollama merges them


def test_the_prefix_for_warming_up_starts_the_next_prompt():
    for turns in ([], [GREETING], [GREETING, SPICY]):  # SPICY ends the history with a filter note
        history = history_messages(turns)
        prefix = prefix_messages(system_prompt="You are Mika.", history=history)
        for memories in (None, memories_block([MOCHI], max_tokens=150)):
            messages = build_turn_messages(
                system_prompt="You are Mika.", history=history, memories=memories, user_message="Hi!", num_predict=150
            )
            assert is_prompt_prefix(prefix, messages)


def test_merge_roles_joins_like_ollama():
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "c"},
    ]
    assert merge_roles(messages) == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "a\n\nb"},
        {"role": "assistant", "content": "c"},
    ]
    assert messages[1] == {"role": "user", "content": "a"}  # the input is left alone


def test_cache_keeps_the_latest_turns_per_user():
    cache = ConversationCache(max_turns=2)
    for turn in (GREETING, SPICY, GREETING):
        cache.add("admin", turn)
    cache.add("someone", SPICY)
    assert cache.recent("admin") == [SPICY, GREETING]
    assert cache.recent("someone") == [SPICY]
    assert cache.recent("nobody") == []
    cache.seed("admin", [GREETING, SPICY, GREETING, SPICY])  # seeding respects the size too
    assert cache.recent("admin") == [GREETING, SPICY]


def same_size_turns(count: int) -> list[Turn]:
    """Distinct turns that cost the same number of tokens."""
    return [Turn(f"Message {chr(65 + i)}", GREETING.result) for i in range(count)]


def test_the_window_grows_then_restarts_with_the_newest_turns():
    t1, t2, t3, t4, t5 = same_size_turns(5)
    cost = turn_tokens(t1)
    budget = 3 * cost + 1  # three turns fit; half of it fits one
    cache = ConversationCache(max_turns=6)
    windows = []
    for turn in (t1, t2, t3, t4, t5):
        cache.add("admin", turn)
        windows.append(cache.window("admin", budget))
    assert windows == [[t1], [t1, t2], [t1, t2, t3], [t4], [t4, t5]]
    assert cache.window("admin", budget) == [t4, t5]  # the same until a turn is added


def test_the_window_restarts_when_its_first_turn_leaves_the_cache():
    t1, t2, t3 = same_size_turns(3)
    cache = ConversationCache(max_turns=2)
    cache.add("admin", t1)
    cache.add("admin", t2)
    assert cache.window("admin", 10_000) == [t1, t2]
    cache.add("admin", t3)  # t1 leaves the cache
    assert cache.window("admin", 10_000) == [t2, t3]


def test_a_turn_too_big_for_half_the_budget_still_fits_whole():
    (turn,) = same_size_turns(1)
    cache = ConversationCache(max_turns=6)
    cache.add("admin", turn)
    assert cache.window("admin", turn_tokens(turn)) == [turn]
    assert cache.window("admin", turn_tokens(turn) - 1) == []


def test_filtered_turns_get_a_note_but_allowed_ones_do_not():
    assert [m["role"] for m in turn_messages(GREETING)] == ["user", "assistant"]
    assert turn_messages(SPICY)[-1] == {"role": "user", "content": NOTE}
    assert turn_tokens(SPICY) == sum(message_tokens(m) for m in turn_messages(SPICY))


def test_history_text_for_the_filter():
    text = history_text([GREETING, SPICY], speaker="Pandora", assistant="Mika-sama", max_turns=1)
    assert text == "Pandora: Say something spicy.\nMika-sama: Filtered! Let's talk about games instead."
    assert history_text([GREETING], speaker="Pandora", assistant="Mika-sama", max_turns=0) == ""


def test_memories_respect_their_budget():
    assert memories_block([], max_tokens=150) is None
    one = memories_block([MOCHI], max_tokens=150)
    assert memories_block([MOCHI, "x" * 600], max_tokens=150) == one  # the second doesn't fit
    assert memories_block([MOCHI], max_tokens=10) is None


def test_an_overlong_message_still_fits_the_context():
    huge = "word " * 5000
    messages = build_turn_messages(
        system_prompt="You are Mika.",
        history=turn_messages(GREETING),
        memories="[memories]",
        user_message=huge,
        num_predict=150,
    )
    assert [m["role"] for m in messages] == ["system", "user"]
    assert sum(message_tokens(m) for m in messages) <= CONTEXT_TOKENS - 150
    assert huge.startswith(messages[1]["content"])


def test_history_is_dropped_before_the_message_is_shortened():
    long_message = "word " * 2900  # fits alone, but not together with the history
    messages = build_turn_messages(
        system_prompt="You are Mika.",
        history=turn_messages(GREETING) * 40,
        memories=None,
        user_message=long_message,
        num_predict=150,
    )
    assert messages == [{"role": "system", "content": "You are Mika."}, {"role": "user", "content": long_message}]
