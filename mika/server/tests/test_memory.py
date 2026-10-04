from app.memory.cache import ConversationCache
from app.memory.history import history_messages, history_text, turn_messages
from app.memory.prompt import CONTEXT_TOKENS, build_turn_messages
from app.memory.rag import memories_message
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


def test_full_prompt_for_a_user_with_a_past_filtered_turn():
    """Plan, Phase 5 "done when": the whole prompt, message by message."""
    personality = Personality(name="Mika-sama", role="AI VTuber", core_identity="You are Mika-sama.", guidelines=["Be kind."])
    system_prompt = build_system_prompt(personality, traits=["Loves rainy days"])
    messages = build_turn_messages(
        system_prompt=system_prompt,
        history=history_messages([GREETING, SPICY], max_tokens=350),
        memories=memories_message([MOCHI], max_tokens=150),
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
            "role": "system",
            "content": "Note: the stream's filter changed your reply above (REPLACE). "
            "What you originally wrote: Something spicy.",
        },
        {
            "role": "system",
            "content": "Things you remember from earlier conversations (they may be old):\n"
            "- Pandora: I adopted a cat named Mochi. / Mika-sama: Mochi is the cutest name!",
        },
        {"role": "user", "content": "How is Mochi doing?"},
    ]
    assert system_prompt.index("You are Mika-sama.") < system_prompt.index("- Loves rainy days")


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


def test_history_drops_whole_turns_oldest_first():
    latest_only = sum(message_tokens(m) for m in turn_messages(SPICY))
    assert history_messages([GREETING, SPICY], max_tokens=latest_only) == turn_messages(SPICY)
    assert history_messages([GREETING, SPICY], max_tokens=latest_only - 1) == []


def test_blocked_and_replaced_turns_get_a_note_but_allowed_ones_do_not():
    assert [m["role"] for m in turn_messages(GREETING)] == ["user", "assistant"]
    assert [m["role"] for m in turn_messages(SPICY)] == ["user", "assistant", "system"]


def test_history_text_for_the_filter():
    text = history_text([GREETING, SPICY], speaker="Pandora", assistant="Mika-sama", max_turns=1)
    assert text == "Pandora: Say something spicy.\nMika-sama: Filtered! Let's talk about games instead."
    assert history_text([GREETING], speaker="Pandora", assistant="Mika-sama", max_turns=0) == ""


def test_memories_respect_their_budget():
    assert memories_message([], max_tokens=150) is None
    one = memories_message([MOCHI], max_tokens=150)
    assert memories_message([MOCHI, "x" * 600], max_tokens=150) == one  # the second doesn't fit
    assert memories_message([MOCHI], max_tokens=10) is None


def test_an_overlong_message_still_fits_the_context():
    huge = "word " * 5000
    messages = build_turn_messages(
        system_prompt="You are Mika.",
        history=turn_messages(GREETING),
        memories={"role": "system", "content": "memories"},
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
