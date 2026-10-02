"""From the LLM's token stream to Mika's emotion and spoken sentences.

The Mac-side pipeline from the spec, up to the output filter:
    token stream -> emotion tag parser -> normalizer -> sentence chunker
"""

from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass

from mika_shared.enums import Emotion

from ..filter.normalizer import TextNormalizer
from .chunker import SentenceChunker
from .tag_parser import EmotionTagParser


@dataclass(frozen=True)
class EmotionDecided:
    """Always the first event: the reply's emotion, known as soon as the tag (or its absence) is."""

    emotion: Emotion
    tag_found: bool


@dataclass(frozen=True)
class SentenceReady:
    text: str


ReplyEvent = EmotionDecided | SentenceReady


async def reply_events(tokens: AsyncIterable[str]) -> AsyncIterator[ReplyEvent]:
    tags, normalizer, chunker = EmotionTagParser(), TextNormalizer(), SentenceChunker()
    announced = False

    async for token in tokens:
        text = tags.feed(token)
        if tags.decided and not announced:
            announced = True
            yield EmotionDecided(tags.emotion, tags.tag_found)
        for sentence in chunker.feed(normalizer.feed(text)):
            yield SentenceReady(sentence)

    text = tags.finish()
    if not announced:
        yield EmotionDecided(tags.emotion, tags.tag_found)
    sentences = chunker.feed(normalizer.feed(text) + normalizer.finish()) + chunker.finish()
    for sentence in sentences:
        yield SentenceReady(sentence)
