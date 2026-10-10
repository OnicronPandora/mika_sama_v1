import pytest
from fakes import FakeEngine

from app.config import FilterSettings
from app.filter.context import TurnContext
from app.filter.replacer import Replacer, clean_line

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
