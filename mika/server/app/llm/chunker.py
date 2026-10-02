"""State-buffered sentence chunking (spec: Streaming Text System), using English punctuation rules.

- A sentence ends at . ! or ? (plus any closing quotes or brackets), followed by whitespace and then a
  character that can start a sentence: anything but a lowercase letter.
- These are not sentence ends: abbreviations (Mr., Dr., e.g., a.m., ...), single-letter initials (J. K.),
  decimals (3.14 has no space), and the ellipsis "...", which is a pause inside a sentence.
- A sentence longer than MAX_SENTENCE characters is split at its last comma, semicolon or colon (else its
  last space), so the TTS never has to wait for one huge sentence.
- finish() flushes the rest at the end of the stream.

The sentences don't depend on how the text was divided into chunks.
"""

import re

MAX_SENTENCE = 220
MIN_SPLIT = 60  # a forced split never leaves a first part shorter than this

_CLOSERS = "\"')]"
_CANDIDATE = re.compile(r"[.!?]+[\"')\]]*(?=(\s+)(\S))")  # an end mark, confirmed by what follows it
_PENDING = re.compile(r"[.!?]+[\"')\]]*\s*$")  # an end mark still waiting for the next character
_TOKEN_BEFORE = re.compile(r"(\S+)$")
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "vs", "approx", "fig",
    "e.g", "i.e", "a.m", "p.m", "u.s", "u.k",
}


class SentenceChunker:
    """Feed the normalized reply text in order; ``feed`` and ``finish`` return the completed sentences."""

    def __init__(self, max_sentence: int = MAX_SENTENCE) -> None:
        self._buffer = ""
        self._max = max_sentence

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        sentences = []
        while (sentence := self._next_sentence()) is not None:
            if sentence:
                sentences.append(sentence)
        return sentences

    def finish(self) -> list[str]:
        """Call at the end of the stream; returns the last sentence(s)."""
        sentences = self.feed("")
        rest, self._buffer = self._buffer.strip(), ""
        return [*sentences, rest] if rest else sentences

    def _next_sentence(self) -> str | None:
        """Cut the first complete sentence off the buffer, or return None if there isn't one yet."""
        boundary = self._find_boundary()
        if boundary is not None and boundary[0] <= self._max:
            cut, resume = boundary
        elif len(self._buffer) > self._max and not self._pending_end_within_limit():
            cut = resume = self._forced_split()
        else:
            return None
        sentence = self._buffer[:cut].strip()
        self._buffer = self._buffer[resume:].lstrip()
        return sentence

    def _find_boundary(self) -> tuple[int, int] | None:
        for match in _CANDIDATE.finditer(self._buffer):
            mark = match.group(0).rstrip(_CLOSERS)
            if "..." in mark or match.group(2).islower():
                continue
            if mark == "." and self._is_abbreviation(match.start()):
                continue
            return match.end(), match.end() + len(match.group(1))
        return None

    def _is_abbreviation(self, period: int) -> bool:
        token_match = _TOKEN_BEFORE.search(self._buffer[:period])
        token = token_match.group(1).lstrip("\"'([") if token_match else ""
        if len(token) == 1 and token.isalpha() and token.isupper() and token != "I":
            return True  # an initial, as in "J. K. Rowling"
        return token.lower() in _ABBREVIATIONS

    def _pending_end_within_limit(self) -> bool:
        """An end mark at the very end of the buffer may still be confirmed by the next character."""
        pending = _PENDING.search(self._buffer)
        return pending is not None and pending.start() < self._max

    def _forced_split(self) -> int:
        window = self._buffer[: self._max]
        clause_end = max(window.rfind(sep) for sep in (", ", "; ", ": "))
        if clause_end >= MIN_SPLIT:
            return clause_end + 1  # keep the comma with the first part
        space = window.rfind(" ")
        return space if space >= MIN_SPLIT else self._max
