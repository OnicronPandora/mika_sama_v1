import pytest

from app.filter.normalizer import MAX_ACTION, TextNormalizer


def normalize(chunks: list[str]) -> str:
    normalizer = TextNormalizer()
    return "".join(normalizer.feed(chunk) for chunk in chunks) + normalizer.finish()


LONG_TAIL = "x" * (MAX_ACTION + 10)

CASES = [
    ("Hi there!", "Hi there!"),
    ("*giggles* Hi!", "Hi!"),
    ("Hi! *waves happily* How are you?", "Hi! How are you?"),
    ("That's **so** cool", "That's so cool"),
    ("I love it 😀🎉!", "I love it!"),
    ("Thumbs up 👍🏽 and ❤️ hearts", "Thumbs up and hearts"),
    ("“Quoted” and it’s fine…", "\"Quoted\" and it's fine..."),
    ("wait—what?", "wait, what?"),
    ("wait — what?", "wait, what?"),
    ("Fullwidth！", "Fullwidth!"),
    ("  lots   of\n\nspace  ", "lots of space"),
    ("before , and . after", "before, and. after"),
    ("Ehehe~ so fun", "Ehehe~ so fun"),
    ("2 * 3 = 6", "2 3 = 6"),  # a lone asterisk is dropped, not treated as a stage direction
    ("a stray *asterisk " + LONG_TAIL, "a stray asterisk " + LONG_TAIL),
    ("ends with a star *", "ends with a star"),
    ("an open *action at the end", "an open action at the end"),
]


@pytest.mark.parametrize(("raw", "clean"), CASES)
def test_whole_text(raw, clean):
    assert normalize([raw]) == clean


@pytest.mark.parametrize(("raw", "clean"), CASES)
def test_one_character_at_a_time(raw, clean):
    assert normalize(list(raw)) == clean


def test_stage_direction_split_across_tokens():
    assert normalize(["Hi! *gig", "gles", "* How", " are you?"]) == "Hi! How are you?"


def test_text_flows_without_waiting():
    normalizer = TextNormalizer()
    assert normalizer.feed("Hello") == "Hello"
    assert normalizer.feed(" world") == " world"
