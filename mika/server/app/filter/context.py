"""What the output filter knows about the turn while it checks a sentence."""

from dataclasses import dataclass

from mika_shared.enums import Emotion


@dataclass(frozen=True)
class TurnContext:
    user_message: str
    history: str = ""  # recent turns as text (what the "separate" classifier sees)
    reply_so_far: str = ""  # what Mika has actually said so far in this reply, after filtering
    prompt: tuple[dict[str, str], ...] = ()  # the turn's chat messages; the "shared" calls continue them
    emotion: Emotion = Emotion.NEUTRAL

    def reply_with(self, sentence: str = "") -> str:
        """Mika's reply as it appears in her conversation: the emotion tag, what she has said, then sentence."""
        return " ".join(part for part in (f"[{self.emotion.value}]", self.reply_so_far, sentence) if part)
