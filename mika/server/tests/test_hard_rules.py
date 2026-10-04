import pytest

from app.filter.hard_rules import PROHIBITED_WORDS_FILE, ProhibitedWords

WORDS = ProhibitedWords(["ass", "curse*", "shut up", "Fück"])


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("You're a pain in the ass!", "ass"),
        ("ASS", "ass"),
        ("This class is fun.", None),  # whole words only
        ("Assume nothing.", None),
        ("He cursed loudly.", "cursed"),  # trailing * matches longer words
        ("Curse it!", "curse"),
        ("Oh, SHUT   UP already", "shut   up"),  # phrases match with any spacing
        ("Shutting up now.", None),
        ("What the fuck.", "fuck"),  # entries and text ignore accents
        ("What the fück.", "fuck"),
        ("A perfectly nice sentence.", None),
    ],
)
def test_find(text, hit):
    assert WORDS.find(text) == hit


def test_an_empty_list_blocks_nothing():
    assert ProhibitedWords([]).find("anything at all") is None


def test_file_format(tmp_path):
    path = tmp_path / "words.txt"
    path.write_text("# a comment\n\n  darn  \n   # indented comment\nheck*\n", encoding="utf-8")
    words = ProhibitedWords.from_file(path)
    assert words.size == 2
    assert words.find("Darn it, heckin' cute") == "darn"


def test_the_shipped_file_loads():
    assert ProhibitedWords.from_file(PROHIBITED_WORDS_FILE).size >= 0
