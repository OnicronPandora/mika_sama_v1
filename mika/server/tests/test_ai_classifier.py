import pytest
from fakes import FakeEngine, verdict
from pydantic import ValidationError

from app.config import FilterSettings
from app.filter.ai_classifier import VERDICT_SCHEMA, FilterPolicy, SafetyClassifier, Verdict, load_filter_policy
from app.filter.context import TurnContext
from mika_shared.enums import Emotion

POLICY = FilterPolicy(allowed=["teasing and mild flirting"], unsafe=["sexual content", "threats"])
FAST = FilterSettings(classifier_timeout=0.1)
CONTEXT = TurnContext(user_message="Do you like my outfit?", history="Pandora: hi\nMika: hi!", reply_so_far="Ooh!")


def classifier(engine: FakeEngine) -> SafetyClassifier:
    return SafetyClassifier(engine, POLICY, FAST, streamer="Mika-sama")


@pytest.mark.parametrize("safe", [True, False])
async def test_returns_the_verdict(safe):
    engine = FakeEngine(verdict(safe, "because"))
    assert await classifier(engine).classify("A sentence.", CONTEXT) == Verdict(safe, "because")


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ("not json", "classifier error"),
        ('{"reason": "no verdict"}', "classifier gave no clear answer"),
        ('{"safe": "yes", "reason": "a string, not a boolean"}', "classifier gave no clear answer"),
        ("[true]", "classifier gave no clear answer"),
        (ConnectionError("Ollama is down"), "classifier error: ConnectionError"),
        (1.0, "classifier timed out"),
    ],
)
async def test_fails_closed(answer, reason):
    result = await classifier(FakeEngine(answer)).classify("A sentence.", CONTEXT)
    assert (result.safe, result.judged) == (False, False)
    assert result.reason.startswith(reason)


async def test_prompt_has_the_rules_and_the_context_in_cache_friendly_order():
    engine = FakeEngine(verdict(True), verdict(True))
    safety = classifier(engine)
    await safety.classify("First sentence.", CONTEXT)
    await safety.classify("Second sentence.", CONTEXT)
    first, second = engine.calls
    system, user = first.messages
    assert "- teasing and mild flirting" in system["content"]
    assert "- sexual content" in system["content"]
    assert second.messages[0] == system  # unchanged within a turn, so Ollama can reuse it
    parts = ["Do you like my outfit?", "Mika: hi!", "Ooh!", "SENTENCE: First sentence."]
    positions = [user["content"].index(part) for part in parts]
    assert positions == sorted(positions)  # what changes most comes last
    assert (first.temperature, first.json_schema["required"]) == (0, ["safe", "reason"])


def test_the_shipped_policy_file_is_valid():
    policy = load_filter_policy()
    assert policy.allowed and policy.unsafe


def test_a_typo_in_the_policy_file_is_an_error(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("allowed: [a]\nunsafe: [b]\nunsafe_extra: [c]\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_filter_policy(path)


SHARED = FilterSettings(classifier_timeout=0.1, context_mode="shared")
PROMPT = (
    {"role": "system", "content": "You are Mika-sama.\n\nStream rules ..."},
    {"role": "user", "content": "Do you like my outfit?"},
)


async def test_shared_mode_continues_mikas_conversation():
    engine = FakeEngine(verdict(True))
    context = TurnContext(user_message="Do you like my outfit?", reply_so_far="Ooh!", prompt=PROMPT, emotion=Emotion.HAPPY)
    assert await SafetyClassifier(engine, POLICY, SHARED, streamer="Mika-sama").classify("It's cute!", context) == Verdict(True, "test")
    (call,) = engine.calls
    assert call.messages[:2] == list(PROMPT)  # what Ollama has just read for her reply
    assert call.messages[2] == {"role": "assistant", "content": "[happy] Ooh! It's cute!"}
    check = call.messages[3]
    assert check["role"] == "user"
    assert check["content"].startswith("[Message from the stream's safety filter")
    assert '"It\'s cute!"' in check["content"]
    # The rules sit right next to the question, and the verdict follows its reason.
    assert check["content"].index("- teasing and mild flirting") < check["content"].index("- sexual content")
    assert list(call.json_schema["properties"]) == ["reason", "safe"]
    assert (call.temperature, call.label) == (0, "classify")


async def test_separate_mode_gives_the_verdict_first():
    engine = FakeEngine(verdict(True))
    await classifier(engine).classify("A sentence.", CONTEXT)
    assert engine.calls[0].json_schema == VERDICT_SCHEMA


async def test_shared_mode_needs_the_turn_prompt():
    with pytest.raises(ValueError):
        await SafetyClassifier(FakeEngine(), POLICY, SHARED, streamer="Mika-sama").classify("Hi.", CONTEXT)


def test_the_rules_as_a_section_of_mikas_prompt():
    section = POLICY.prompt_section()
    assert section.startswith("Stream rules")
    assert section.index("- teasing and mild flirting") < section.index("Not allowed") < section.index("- threats")
