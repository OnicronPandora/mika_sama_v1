import random

import pytest

from app.llm.chunker import MAX_SENTENCE, MIN_SPLIT, SentenceChunker


def chunk(pieces: list[str]) -> list[str]:
    chunker = SentenceChunker()
    sentences = [s for piece in pieces for s in chunker.feed(piece)]
    return sentences + chunker.finish()


CASES = [
    ("Hi everyone! How are you? I'm great.", ["Hi everyone!", "How are you?", "I'm great."]),
    ("Really?! No way!", ["Really?!", "No way!"]),
    ("Mr. Smith met Dr. Who. They talked.", ["Mr. Smith met Dr. Who.", "They talked."]),
    ("I like games, e.g. Minecraft. Do you?", ["I like games, e.g. Minecraft.", "Do you?"]),
    ("We start at 9 a.m. Tomorrow too.", ["We start at 9 a.m. Tomorrow too."]),
    ("J. K. Rowling wrote it. Cool.", ["J. K. Rowling wrote it.", "Cool."]),
    ("So did I. Then we left.", ["So did I.", "Then we left."]),
    ("Pi is 3.14 and that's neat. Right?", ["Pi is 3.14 and that's neat.", "Right?"]),
    ("Hmm... I think so. Yes!", ["Hmm... I think so.", "Yes!"]),
    ("Well... maybe.", ["Well... maybe."]),
    ('She said "wow!" Then she left.', ['She said "wow!"', "Then she left."]),
    ("(Like this.) Next one.", ["(Like this.)", "Next one."]),
    ("so cool. and then more", ["so cool. and then more"]),  # lowercase after the period: same sentence
    ("No final punctuation", ["No final punctuation"]),
    ("Trailing space after the end. ", ["Trailing space after the end."]),
    ("", []),
]


@pytest.mark.parametrize(("text", "sentences"), CASES)
def test_whole_text(text, sentences):
    assert chunk([text]) == sentences


@pytest.mark.parametrize(("text", "sentences"), CASES)
def test_one_character_at_a_time(text, sentences):
    assert chunk(list(text)) == sentences


def test_a_sentence_is_released_once_the_next_one_starts():
    chunker = SentenceChunker()
    assert chunker.feed("Hi! ") == []  # could still be "Hi! hello" (not a sentence end)
    assert chunker.feed("How") == ["Hi!"]
    assert chunker.finish() == ["How"]


def test_long_sentences_are_split_at_a_comma():
    clause = "and then we kept talking about games and anime for a while, "
    text = "Well, " + clause * 5 + "the end."
    sentences = chunk([text])
    assert len(sentences) > 1
    assert all(len(s) <= MAX_SENTENCE for s in sentences)
    assert all(s.endswith(",") for s in sentences[:-1])
    assert all(len(s) >= MIN_SPLIT for s in sentences[:-1])
    assert " ".join(sentences) == text.strip()


def test_a_long_run_without_commas_is_split_at_a_space():
    text = " ".join(["word"] * 80) + "."
    sentences = chunk([text])
    assert all(len(s) <= MAX_SENTENCE for s in sentences)
    assert " ".join(sentences) == text


def test_sentences_do_not_depend_on_chunk_boundaries():
    text = (
        "Hi Pandora! Mr. Smith said the score was 3.14, e.g. close to pi... Wow. "
        + "This one keeps going, " * 12
        + 'and finally ends here. "Really?!" (Yes.) ok then. The end'
    )
    expected = chunk([text])
    rng = random.Random(42)
    for _ in range(200):
        cuts = sorted(rng.sample(range(1, len(text)), rng.randint(1, 30)))
        pieces = [text[a:b] for a, b in zip([0, *cuts], [*cuts, len(text)])]
        assert chunk(pieces) == expected
