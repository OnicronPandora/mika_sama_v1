"""Test doubles for the LLM engine."""

import asyncio
import json
from dataclasses import dataclass


@dataclass
class Call:
    messages: list[dict[str, str]]
    temperature: float
    num_predict: int
    json_schema: dict | None


class FakeEngine:
    """Answers complete() calls from a script, in order. An answer is a string to return, an exception to
    raise, or a number of seconds to hang (to trigger a timeout)."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.calls: list[Call] = []

    async def complete(self, messages, *, temperature, num_predict, json_schema=None) -> str:
        self.calls.append(Call(list(messages), temperature, num_predict, json_schema))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, (int, float)):
            await asyncio.sleep(answer)
            return ""
        return answer

    @property
    def classifier_calls(self) -> list[Call]:
        return [call for call in self.calls if call.json_schema]

    @property
    def replacer_calls(self) -> list[Call]:
        return [call for call in self.calls if not call.json_schema]


def verdict(safe: bool, reason: str = "test") -> str:
    """A classifier answer as Ollama returns it."""
    return json.dumps({"safe": safe, "reason": reason})
