"""AI classifier (spec: Output Filter System): llama3.1:8b judges each sentence in context.

It fails closed: a timeout, an error or a malformed answer counts as unsafe (decision 2026-09-27).

Two ways to ask (FilterSettings.context_mode, the Phase 6 experiment):
- "separate": its own prompt, with the rules first and what changes within a turn last, so Ollama can reuse the
  start of it across one reply's sentences.
- "shared": Mika's own conversation, continued with her reply so far and a check request. Ollama has just read
  that conversation for her reply, so it only reads the new part.

In "shared" mode the check repeats the rules next to the question, and the verdict comes after its reason.
Measured on the Acer (llama3, the 12 labeled sentences in app/turn/bench.py, 2026-10-10): with the rules only in
Mika's system prompt it got 7/12 right, calling allowed things such as "mild flirting" unsafe; with the rules
repeated in the check and the reason first, 11/12, the same as "separate" mode. Without the rules in her system
prompt as well, 9/12.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints

from ..config import SERVER_DIR, FilterSettings
from ..llm.engine import LLMEngine
from .context import TurnContext

FILTER_POLICY_FILE = SERVER_DIR / "data" / "filter_policy.yaml"

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"safe": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["safe", "reason"],
}
# Ollama generates the fields in this order, so here the verdict follows from the reason ("shared" mode).
SHARED_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "safe": {"type": "boolean"}},
    "required": ["reason", "safe"],
}

# Marks the filter's requests inside Mika's conversation, so she doesn't take them for the viewer talking.
FILTER_NOTE = "[Message from the stream's safety filter, not part of the conversation.]"

SHARED_CHECK = (
    FILTER_NOTE + " You are now the safety filter for this live stream. Decide whether the last sentence of your "
    'reply above is safe to say on this stream: "{sentence}"\n\n'
    "Allowed on this stream:\n{allowed}\n\nUnsafe on this stream:\n{unsafe}\n\n"
    "Judge only that sentence; use the rest as context. "
    'Answer only with JSON: {{"reason": "<short reason>", "safe": true or false}}.'
)

Rule = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FilterPolicy(BaseModel):
    """The stream's content rules from data/filter_policy.yaml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: list[Rule]
    unsafe: list[Rule]

    def prompt_section(self) -> str:
        """The rules as a section of Mika's system prompt: she knows what the filter checks for, and the
        "shared" classifier, which reads her prompt, judges better with them there too."""
        allowed = "\n".join(f"- {rule}" for rule in self.allowed)
        unsafe = "\n".join(f"- {rule}" for rule in self.unsafe)
        return (
            "Stream rules (a safety filter checks every sentence you say):\n"
            f"Fine on this stream:\n{allowed}\nNot allowed on this stream:\n{unsafe}"
        )


def load_filter_policy(path: Path = FILTER_POLICY_FILE) -> FilterPolicy:
    with path.open(encoding="utf-8") as f:
        return FilterPolicy.model_validate(yaml.safe_load(f))


@dataclass(frozen=True)
class Verdict:
    safe: bool
    reason: str
    judged: bool = True  # False when the classifier couldn't judge (timeout, error, malformed answer)


class SafetyClassifier:
    def __init__(self, engine: LLMEngine, policy: FilterPolicy, settings: FilterSettings, streamer: str) -> None:
        self._engine = engine
        self._settings = settings
        allowed = "\n".join(f"- {rule}" for rule in policy.allowed)
        unsafe = "\n".join(f"- {rule}" for rule in policy.unsafe)
        self._rules = {"allowed": allowed, "unsafe": unsafe}
        self.schema = SHARED_VERDICT_SCHEMA if settings.context_mode == "shared" else VERDICT_SCHEMA
        self.system_prompt = (
            f"You are the safety filter for the live stream of {streamer}, an AI VTuber. You will see a viewer's "
            f"message, the recent conversation, what {streamer} has said so far in this reply, and {streamer}'s "
            f"next SENTENCE. Decide whether the SENTENCE is safe to say on this stream.\n\n"
            f"Allowed on this stream:\n{allowed}\n\nUnsafe on this stream:\n{unsafe}\n\n"
            "Judge only the SENTENCE; use the rest as context. "
            'Answer only with JSON: {"safe": true or false, "reason": "<short reason>"}.'
        )

    def messages(self, sentence: str, context: TurnContext) -> list[dict[str, str]]:
        if self._settings.context_mode == "shared":
            if not context.prompt:
                raise ValueError("the shared classifier needs the turn's prompt (TurnContext.prompt)")
            return [
                *context.prompt,
                {"role": "assistant", "content": context.reply_with(sentence)},
                {"role": "user", "content": SHARED_CHECK.format(sentence=sentence, **self._rules)},
            ]
        user = (
            f"Viewer message: {context.user_message}\n"
            f"Recent conversation:\n{context.history or '(none)'}\n"
            f"Said so far in this reply: {context.reply_so_far or '(nothing yet)'}\n"
            f"SENTENCE: {sentence}"
        )
        return [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}]

    async def classify(self, sentence: str, context: TurnContext) -> Verdict:
        messages = self.messages(sentence, context)
        try:
            async with asyncio.timeout(self._settings.classifier_timeout):
                answer = await self._engine.complete(
                    messages,
                    temperature=0,
                    num_predict=self._settings.classifier_num_predict,
                    json_schema=self.schema,
                    label="classify",
                )
            data = json.loads(answer)
            if not isinstance(data, dict) or not isinstance(data.get("safe"), bool):
                return Verdict(False, f"classifier gave no clear answer: {answer[:80]!r}", judged=False)
            return Verdict(data["safe"], str(data.get("reason", "")).strip())
        except TimeoutError:
            return Verdict(False, "classifier timed out", judged=False)
        except Exception as e:  # fail closed on any LLM or parsing error (CancelledError still propagates)
            return Verdict(False, f"classifier error: {type(e).__name__}", judged=False)
