import pytest

from app.llm.tag_parser import MAX_LOOKAHEAD, EmotionTagParser
from mika_shared.enums import Emotion

HAPPY, SAD, CONFUSED, ANGRY, NEUTRAL = Emotion.HAPPY, Emotion.SAD, Emotion.CONFUSED, Emotion.ANGRY, Emotion.NEUTRAL


def parse(chunks: list[str]) -> tuple[Emotion | None, bool, str]:
    parser = EmotionTagParser()
    spoken = "".join(parser.feed(chunk) for chunk in chunks) + parser.finish()
    return parser.emotion, parser.tag_found, spoken


# (reply, emotion, valid tag found, text passed on)
CASES = [
    ("[happy] Hi everyone!", HAPPY, True, "Hi everyone!"),
    ("[Happy] Hi!", HAPPY, True, "Hi!"),
    ("[ SAD ]Oh no.", SAD, True, "Oh no."),
    ("  \n[confused] Huh?", CONFUSED, True, "Huh?"),
    ("(angry) Hey!", ANGRY, True, "Hey!"),
    ("*neutral* Okay.", NEUTRAL, True, "Okay."),
    ("[excited] Wow!", NEUTRAL, False, "Wow!"),  # invalid tag: removed, neutral
    ("[] Hi", NEUTRAL, False, "Hi"),
    ("Hi everyone!", NEUTRAL, False, "Hi everyone!"),  # no tag
    # A bare emotion word that leaked instead of a tag (seen with llama3 in Spike A)
    ("Happy Ah, I'm feeling great!", HAPPY, True, "Ah, I'm feeling great!"),
    ("Sad I'm sorry to hear that.", SAD, True, "I'm sorry to hear that."),
    ("Sad: that's too bad.", SAD, True, "that's too bad."),
    ("Angry - Hey!", ANGRY, True, "Hey!"),
    ("happy\nHi!", HAPPY, True, "Hi!"),
    # Ordinary text that happens to start with an emotion word stays as it is
    ("Happy birthday, Pandora!", NEUTRAL, False, "Happy birthday, Pandora!"),
    ("Happy New Year!", NEUTRAL, False, "Happy New Year!"),
    ("Happy!", NEUTRAL, False, "Happy!"),
    ("Happy-go-lucky me.", NEUTRAL, False, "Happy-go-lucky me."),
    ("Sad to hear that.", NEUTRAL, False, "Sad to hear that."),
    ("Happy", NEUTRAL, False, "Happy"),
    # Brackets that aren't emotions are left for the normalizer
    ("(sigh) Fine.", NEUTRAL, False, "(sigh) Fine."),
    ("*giggles* Hi!", NEUTRAL, False, "*giggles* Hi!"),
    # Edges
    ("[happy]", HAPPY, True, ""),
    ("", NEUTRAL, False, ""),
]


@pytest.mark.parametrize(("reply", "emotion", "found", "spoken"), CASES)
def test_whole_reply(reply, emotion, found, spoken):
    assert parse([reply]) == (emotion, found, spoken)


@pytest.mark.parametrize(("reply", "emotion", "found", "spoken"), CASES)
def test_one_character_at_a_time(reply, emotion, found, spoken):
    assert parse(list(reply)) == (emotion, found, spoken)


def test_tag_split_across_tokens():
    assert parse(["[ha", "ppy", "]", " Hi", " there"]) == (HAPPY, True, "Hi there")


def test_decides_as_soon_as_the_tag_closes():
    parser = EmotionTagParser()
    assert parser.feed("[sa") == ""
    assert not parser.decided
    assert parser.feed("d]") == ""
    assert parser.decided
    assert parser.emotion is SAD


def test_decides_at_once_when_there_is_no_tag():
    parser = EmotionTagParser()
    assert parser.feed("Hello") == "Hello"
    assert parser.emotion is NEUTRAL


def test_waits_while_the_first_word_could_become_an_emotion():
    parser = EmotionTagParser()
    assert parser.feed("Hap") == ""
    assert parser.feed("py Ah,") == "Ah,"
    assert parser.emotion is HAPPY


def test_an_unclosed_bracket_stops_the_wait():
    reply = "[" + "x" * (MAX_LOOKAHEAD + 5) + " and more"
    parser = EmotionTagParser()
    assert parser.feed(reply) == reply
    assert parser.emotion is NEUTRAL


def test_records_an_invalid_tag():
    parser = EmotionTagParser()
    parser.feed("[Excited] Wow")
    assert (parser.raw_tag, parser.tag_found, parser.emotion) == ("excited", False, NEUTRAL)
