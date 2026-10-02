from app.llm.streaming import EmotionDecided, SentenceReady, reply_events
from mika_shared.enums import Emotion


async def tokens(parts: list[str], consumed: list[str] | None = None):
    for part in parts:
        if consumed is not None:
            consumed.append(part)
        yield part


async def collect(parts: list[str]) -> list:
    return [event async for event in reply_events(tokens(parts))]


async def test_emotion_first_then_clean_sentences():
    events = await collect(["[hap", "py] Hi Pan", "dora! *giggles* How was", " your day?"])
    assert events == [
        EmotionDecided(Emotion.HAPPY, True),
        SentenceReady("Hi Pandora!"),
        SentenceReady("How was your day?"),
    ]


async def test_emotion_is_announced_as_soon_as_the_tag_closes():
    consumed: list[str] = []
    events = reply_events(tokens(["[sad]", " Oh no", ", that's", " sad."], consumed))
    assert await anext(events) == EmotionDecided(Emotion.SAD, True)
    assert consumed == ["[sad]"]  # before any sentence text has arrived
    assert [event async for event in events] == [SentenceReady("Oh no, that's sad.")]


async def test_no_tag_means_neutral():
    events = await collect(["Hello there. ", "Bye."])
    assert events == [EmotionDecided(Emotion.NEUTRAL, False), SentenceReady("Hello there."), SentenceReady("Bye.")]


async def test_empty_reply():
    assert await collect([]) == [EmotionDecided(Emotion.NEUTRAL, False)]


async def test_reply_with_only_a_tag():
    assert await collect(["[confused]"]) == [EmotionDecided(Emotion.CONFUSED, True)]
