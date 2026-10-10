"""Personality Prompt Engine (spec: docs/top_secret.md).

The system prompt has three layers, in this order:
1. the base personality from data/personality.yaml (fixed);
2. the traits Mika has learned, from the personality_traits table;
3. the reply rules the streaming pipeline depends on (emotion tag, short spoken sentences).

It is the only system message in Mika's prompts: Ollama moves every system message to the top of the
prompt, so everything that belongs to a turn goes into user and assistant messages (memory/prompt.py).
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints

from mika_shared.enums import Emotion

from ..config import SERVER_DIR

PERSONALITY_FILE = SERVER_DIR / "data" / "personality.yaml"

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_TAGS = ", ".join(f"[{emotion.value}]" for emotion in Emotion)

# Spike A: with this wording llama3.1:8b started 20 of 20 replies with a valid emotion tag.
REPLY_RULES = f"""How to reply:
- You are speaking out loud on a live stream. Answer in 2 to 4 short spoken sentences.
- Do not use emojis, lists, markdown or stage directions such as *laughs*.
- Always start your reply with exactly one emotion tag from this list: {_TAGS}. Example: [happy] Hi everyone, welcome back!"""


class Personality(BaseModel):
    """The base personality file. Unknown keys are rejected so a typo can't silently drop a section."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Text
    role: Text
    core_identity: Text
    guidelines: list[Text]


def load_personality(path: Path = PERSONALITY_FILE) -> Personality:
    with path.open(encoding="utf-8") as f:
        return Personality.model_validate(yaml.safe_load(f))


def build_system_prompt(personality: Personality, traits: Sequence[str] = ()) -> str:
    sections = [personality.core_identity]
    if personality.guidelines:
        sections.append("Guidelines:\n" + "\n".join(f"- {line}" for line in personality.guidelines))
    learned = [trait.strip() for trait in traits if trait.strip()]
    if learned:
        sections.append("What you have learned about yourself:\n" + "\n".join(f"- {trait}" for trait in learned))
    sections.append(REPLY_RULES)
    return "\n\n".join(sections)
