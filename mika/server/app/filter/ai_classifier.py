"""AI classifier (spec: Output Filter System): llama3.1:8b judges each sentence in context.

It fails closed: a timeout, an error or a malformed answer counts as unsafe (decision 2026-09-27).
The prompt puts everything that doesn't change within a turn first, so Ollama can reuse its cache across
the classifier calls for one reply.
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

Rule = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FilterPolicy(BaseModel):
    """The stream's content rules from data/filter_policy.yaml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: list[Rule]
    unsafe: list[Rule]


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
        self.system_prompt = (
            f"You are the safety filter for the live stream of {streamer}, an AI VTuber. You will see a viewer's "
            f"message, the recent conversation, what {streamer} has said so far in this reply, and {streamer}'s "
            f"next SENTENCE. Decide whether the SENTENCE is safe to say on this stream.\n\n"
            f"Allowed on this stream:\n{allowed}\n\nUnsafe on this stream:\n{unsafe}\n\n"
            "Judge only the SENTENCE; use the rest as context. "
            'Answer only with JSON: {"safe": true or false, "reason": "<short reason>"}.'
        )

    def messages(self, sentence: str, context: TurnContext) -> list[dict[str, str]]:
        user = (
            f"Viewer message: {context.user_message}\n"
            f"Recent conversation:\n{context.history or '(none)'}\n"
            f"Said so far in this reply: {context.reply_so_far or '(nothing yet)'}\n"
            f"SENTENCE: {sentence}"
        )
        return [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}]

    async def classify(self, sentence: str, context: TurnContext) -> Verdict:
        try:
            async with asyncio.timeout(self._settings.classifier_timeout):
                answer = await self._engine.complete(
                    self.messages(sentence, context),
                    temperature=0,
                    num_predict=self._settings.classifier_num_predict,
                    json_schema=VERDICT_SCHEMA,
                )
            data = json.loads(answer)
            if not isinstance(data, dict) or not isinstance(data.get("safe"), bool):
                return Verdict(False, f"classifier gave no clear answer: {answer[:80]!r}", judged=False)
            return Verdict(data["safe"], str(data.get("reason", "")).strip())
        except TimeoutError:
            return Verdict(False, "classifier timed out", judged=False)
        except Exception as e:  # fail closed on any LLM or parsing error (CancelledError still propagates)
            return Verdict(False, f"classifier error: {type(e).__name__}", judged=False)
