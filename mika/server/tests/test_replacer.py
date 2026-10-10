import pytest
from fakes import FakeEngine

from app.config import FilterSettings
from app.filter.context import TurnContext
from app.filter.replacer import Replacer, clean_line
from mika_shared.enums import Emotion

FAST = FilterSettings(replacer_timeout=0.1)
CONTEXT = TurnContext(user_message="Tell me a secret!", reply_so_far="Ehehe~ okay.")


@pytest.mark.parametrize(
    ("answer", "line"),
    [
        ("Let's talk about games instead!", "Let's talk about games instead!"),
        ('[happy] "Let\'s talk about games instead!" *winks* And more.', "Let's talk about games instead!"),
        ("Ooh 😄 how about anime? It's fun.", "Ooh how about anime?"),
        ("   ", ""),
    ],
)
def test_clean_line(answer, line):
    assert clean_line(answer) == line


async def test_rewrite_never_shows_the_prohibited_word():
    engine = FakeEngine("Let's play a game!")
    line = await Replacer(engine, FAST, persona="Mika-sama, AI VTuber").rewrite(CONTEXT)
    assert line == "Let's play a game!"
    system, user = engine.calls[0].messages
    assert "Mika-sama, AI VTuber" in system["content"]
    assert "prohibited word" in system["content"]
    assert "Tell me a secret!" in user["content"] and "Ehehe~ okay." in user["content"]


async def test_deflect_explains_why():
    engine = FakeEngine("[neutral] Anyway, how was your day?")
    line = await Replacer(engine, FAST, persona="Mika").deflect(CONTEXT, "sexual content")
    assert line == "Anyway, how was your day?"
    assert "(sexual content)" in engine.calls[0].messages[0]["content"]


@pytest.mark.parametrize("answer", ["", "*shrugs*", ConnectionError("down"), 1.0])
async def test_gives_none_when_there_is_nothing_usable(answer):
    assert await Replacer(FakeEngine(answer), FAST, persona="Mika").deflect(CONTEXT, "reason") is None


async def test_shared_mode_continues_mikas_conversation_without_the_filtered_sentence():
    prompt = ({"role": "system", "content": "You are Mika-sama."}, {"role": "user", "content": "Tell me a secret!"})
    context = TurnContext(user_message="Tell me a secret!", reply_so_far="Ehehe~ okay.", prompt=prompt, emotion=Emotion.HAPPY)
    shared = FilterSettings(replacer_timeout=0.1, context_mode="shared")
    engine = FakeEngine("[happy] Let's play a game instead!", "How about anime?")
    replacer = Replacer(engine, shared, persona="Mika-sama, AI VTuber")
    assert await replacer.rewrite(context) == "Let's play a game instead!"
    assert await replacer.deflect(context, "personal information") == "How about anime?"
    rewrite, deflect = engine.calls
    for call in (rewrite, deflect):
        assert call.messages[:2] == list(prompt)
        assert call.messages[2] == {"role": "assistant", "content": "[happy] Ehehe~ okay."}
        assert call.messages[3]["content"].startswith("[Message from the stream's safety filter")
    assert "prohibited word" in rewrite.messages[3]["content"]
    assert "(personal information)" in deflect.messages[3]["content"]
    assert (rewrite.label, deflect.label) == ("rewrite", "deflect")
