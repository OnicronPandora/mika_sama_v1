"""Normalizer: cleans the streamed reply for speech and for the filter (spec: Output Filter System).

Runs on the stream after the emotion tag parser and before the sentence chunker:
- removes stage directions in single asterisks ("*giggles*") and the markers of **bold** text;
- removes emojis and other pictographs;
- turns typographic characters into plain ones (curly quotes, the ellipsis character, fullwidth forms)
  and dashes into commas, which read as a pause;
- collapses whitespace, and never leaves a space before , . ! ? ; :

Text is held back only while an asterisk is unresolved, for at most MAX_ACTION characters.
"""

import unicodedata

MAX_ACTION = 80  # a "*" left open longer than this is a stray asterisk, not a stage direction

_DROP_CATEGORIES = {"So", "Sk", "Cs", "Co", "Cf", "Cn"}  # symbols (emoji), modifiers, format and unassigned
_DROP_CHARS = {"`", "⃣"} | {chr(code) for code in range(0xFE00, 0xFE10)}  # keycap, variation selectors
_TYPOGRAPHY = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"',
        "–": ", ", "—": ", ", "―": ", ",
        "​": " ",  # a zero-width space still separates words
    }
)
_NO_SPACE_BEFORE = set(",.!?;:")


class TextNormalizer:
    """Feed the reply's text in order; pass on what ``feed`` and ``finish`` return."""

    def __init__(self) -> None:
        self._started = False  # emitted any visible character yet
        self._pending_space = False
        self._star = False  # just saw "*": "**" (bold marker) or the start of "*...*"?
        self._action: str | None = None  # text inside an open "*...*"

    def feed(self, text: str) -> str:
        out: list[str] = []
        for char in text:
            self._consume(char, out)
        return "".join(out)

    def finish(self) -> str:
        """Call at the end of the stream; returns any text still held back."""
        out: list[str] = []
        self._star = False  # a lone "*" at the very end is dropped
        if self._action is not None:
            self._abandon_action(out)
        return "".join(out)

    def _consume(self, char: str, out: list[str]) -> None:
        if self._action is not None:
            if char == "*":
                self._action = None  # a complete stage direction: drop it
                self._pending_space = True
            else:
                self._action += char
                if len(self._action) > MAX_ACTION:
                    self._abandon_action(out)
            return
        if self._star:
            self._star = False
            if char == "*":
                return  # "**": a bold marker, dropped; the text around it is kept
            if char.isspace():
                self._emit(char, out)  # "2 * 3": not a stage direction, just drop the "*"
                return
            self._action = char
            return
        if char == "*":
            self._star = True
            return
        self._emit(char, out)

    def _abandon_action(self, out: list[str]) -> None:
        """An opening "*" that never closed: keep its text, without the asterisk."""
        text, self._action = self._action, None
        for char in text:
            self._emit(char, out)

    def _emit(self, char: str, out: list[str]) -> None:
        for c in unicodedata.normalize("NFKC", char).translate(_TYPOGRAPHY):
            if c in _DROP_CHARS or unicodedata.category(c) in _DROP_CATEGORIES:
                continue
            if c.isspace():
                self._pending_space = True
                continue
            if self._pending_space and self._started and c not in _NO_SPACE_BEFORE:
                out.append(" ")
            self._pending_space = False
            self._started = True
            out.append(c)
