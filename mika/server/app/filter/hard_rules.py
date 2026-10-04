"""Hard rules: the prohibited words list (spec: Output Filter System). A hit means BLOCK.

Each entry is a word or phrase. It matches whole words only ("ass" does not match "class"), ignoring case
and accents. A trailing "*" also matches longer words ("curse*" matches "cursed" and "curses").
"""

import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from ..config import SERVER_DIR

PROHIBITED_WORDS_FILE = SERVER_DIR / "data" / "prohibited_words.txt"


def fold(text: str) -> str:
    """Lowercase and strip accents, so "Fück" and "fuck" compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


class ProhibitedWords:
    def __init__(self, entries: Iterable[str]) -> None:
        patterns = []
        for entry in entries:
            entry = fold(entry.strip())
            prefix = entry.endswith("*")
            words = entry.rstrip("*").split()
            if words:
                body = r"\s+".join(re.escape(word) for word in words)
                tail = r"\w*" if prefix else ""
                patterns.append(rf"(?<!\w){body}{tail}(?!\w)")
        self.size = len(patterns)
        self._pattern = re.compile("|".join(patterns)) if patterns else None

    @classmethod
    def from_file(cls, path: Path = PROHIBITED_WORDS_FILE) -> "ProhibitedWords":
        """One entry per line; blank lines and lines starting with # are ignored."""
        lines = path.read_text(encoding="utf-8").splitlines()
        return cls(line for line in lines if line.strip() and not line.lstrip().startswith("#"))

    def find(self, text: str) -> str | None:
        """The first prohibited word or phrase in the text (lowercased), or None."""
        if self._pattern is None:
            return None
        match = self._pattern.search(fold(text))
        return match.group(0) if match else None
