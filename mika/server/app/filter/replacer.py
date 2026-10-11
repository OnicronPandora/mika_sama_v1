"""Replacer: the LLM writes what Mika says instead of a filtered sentence (decisions 2026-09-27, 2026-10-04).

- rewrite (BLOCK, a prohibited word): one safe sentence that carries on the conversation.
- deflect (REPLACE, the classifier said unsafe): one light-hearted line steering elsewhere, spoken after
  "Filtered!".

Both return None when the LLM fails, times out or gives nothing usable; the caller then uses a fallback line.
"""

import asyncio

from ..config import FilterSettings
from ..llm.chunker import SentenceChunker
from ..llm.engine import LLMEngine
from ..llm.tag_parser import EmotionTagParser
from .context import TurnContext
from .normalizer import TextNormalizer


def clean_line(text: str) -> str:
    """The first sentence of an LLM answer, cleaned like a streamed reply (emotion tag, stage directions, emoji)."""
    tags, normalizer, chunker = EmotionTagParser(), TextNormalizer(), SentenceChunker()
    spoken = tags.feed(text) + tags.finish()
    sentences = chunker.feed(normalizer.feed(spoken) + normalizer.finish()) + chunker.finish()
    return sentences[0].strip('"').strip() if sentences else ""


class Replacer:
    def __init__(self, engine: LLMEngine, settings: FilterSettings, persona: str) -> None:
        self._engine = engine
        self._settings = settings
        self._persona = persona  # e.g. "Mika-sama, AI VTuber"

    async def rewrite(self, context: TurnContext) -> str | None:
        """For BLOCK. The prohibited word itself is never shown to the LLM."""
        return await self._ask(
            "Your next sentence was blocked because it contained a prohibited word. "
            "Say one short sentence that carries on the conversation safely instead, without that word.",
            context,
            label="rewrite",
        )

    async def deflect(self, context: TurnContext, reason: str) -> str | None:
        """For REPLACE."""
        return await self._ask(
            f"Your last sentence was filtered as unsuitable for the stream ({reason}). "
            "Say one short, light-hearted sentence that steers the conversation somewhere else, "
            "without repeating or describing what was filtered.",
            context,
            label="deflect",
        )

    async def _ask(self, instruction: str, context: TurnContext, *, label: str) -> str | None:
        system = (
            f"You are {self._persona}, speaking out loud on a live stream. {instruction} "
            "Output only that sentence, without emojis, an emotion tag or stage directions."
        )
        user = (
            f"Viewer message: {context.user_message}\n"
            f"What you have said so far in this reply: {context.reply_so_far or '(nothing yet)'}"
        )
        try:
            async with asyncio.timeout(self._settings.replacer_timeout):
                answer = await self._engine.complete(
                    [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=0.7,
                    num_predict=self._settings.replacer_num_predict,
                    label=label,
                )
        except Exception:  # timeout or LLM error: the caller falls back (CancelledError still propagates)
            return None
        return clean_line(answer) or None
