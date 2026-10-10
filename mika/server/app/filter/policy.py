"""Policy engine (spec: Output Filter System): one verdict per sentence, before it reaches TTS.

    prohibited word   -> BLOCK:   an LLM-written safe sentence, checked again; else a fallback line
    classifier: safe  -> ALLOW
    classifier: not   -> REPLACE: "Filtered!" + an LLM-written line steering elsewhere, checked again;
                                  else "Filtered!" + a fallback line

The classifier fails closed. When it couldn't judge at all (timeout, error, malformed answer), the LLM is
probably struggling, so REPLACE goes straight to the fallback line instead of asking it for more.
"""

import random
from collections.abc import Sequence
from pathlib import Path

from mika_shared.enums import FilterAction
from mika_shared.payloads import FilterResult

from ..config import SERVER_DIR, FilterSettings
from ..llm.engine import LLMEngine
from ..personality.engine import Personality
from .ai_classifier import FilterPolicy, SafetyClassifier, load_filter_policy
from .context import TurnContext
from .hard_rules import ProhibitedWords
from .replacer import Replacer

FALLBACKS_FILE = SERVER_DIR / "data" / "block_fallbacks.txt"


def load_fallbacks(path: Path = FALLBACKS_FILE) -> list[str]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


class OutputFilter:
    def __init__(
        self,
        *,
        words: ProhibitedWords,
        classifier: SafetyClassifier,
        replacer: Replacer,
        fallbacks: Sequence[str],
        filtered_prefix: str,
        rng: random.Random | None = None,
    ) -> None:
        if not fallbacks:
            raise ValueError("the output filter needs at least one fallback line (data/block_fallbacks.txt)")
        self.words = words
        self.classifier = classifier
        self.replacer = replacer
        self.fallbacks = list(fallbacks)
        self.filtered_prefix = filtered_prefix
        self._rng = rng or random.Random()

    async def check(self, sentence: str, context: TurnContext) -> FilterResult:
        if hit := self.words.find(sentence):
            line = await self.replacer.rewrite(context)
            if not (line and await self._is_safe(line, context)):
                line = self._fallback()
            return FilterResult(action=FilterAction.BLOCK, filter_response=line, reason=f"prohibited word: {hit}")

        verdict = await self.classifier.classify(sentence, context)
        if verdict.safe:
            return FilterResult(action=FilterAction.ALLOW)
        line = await self.replacer.deflect(context, verdict.reason) if verdict.judged else None
        if not (line and await self._is_safe(line, context)):
            line = self._fallback()
        return FilterResult(
            action=FilterAction.REPLACE,
            filter_response=f"{self.filtered_prefix} {line}",
            reason=f"classifier: {verdict.reason}",
        )

    async def _is_safe(self, line: str, context: TurnContext) -> bool:
        """The re-check every LLM-written replacement gets before it is spoken."""
        if self.words.find(line):
            return False
        return (await self.classifier.classify(line, context)).safe

    def _fallback(self) -> str:
        return self._rng.choice(self.fallbacks)


def build_output_filter(
    engine: LLMEngine, personality: Personality, settings: FilterSettings, policy: FilterPolicy | None = None
) -> OutputFilter:
    """The filter as configured by the files in data/ (read once, at startup)."""
    return OutputFilter(
        words=ProhibitedWords.from_file(),
        classifier=SafetyClassifier(engine, policy or load_filter_policy(), settings, streamer=personality.name),
        replacer=Replacer(engine, settings, persona=f"{personality.name}, {personality.role}"),
        fallbacks=load_fallbacks(),
        filtered_prefix=settings.filtered_prefix,
    )
