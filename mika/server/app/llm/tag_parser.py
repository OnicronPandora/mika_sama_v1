"""Reads the emotion tag at the start of a streamed reply (spec: Emotion Manager).

The LLM is told to begin every reply with one tag such as "[happy]". The parser holds back the start of the
stream until it can tell whether a tag is there, removes the tag so it is never spoken, and decides the
emotion. A missing or invalid tag means NEUTRAL: the LLM is not the source of truth.

Recognised: "[happy]" in any capitalisation or spacing, "(happy)", "*happy*", and a bare leading word that is
clearly a tag: "Happy: ...", "Happy - ...", or "Happy Ah, ..." (followed by a typical reply opener). Text such
as "Happy birthday!" or "Happy New Year!" is left alone. Anything else in square brackets at the start, like
"[excited]", is removed as an invalid tag.
"""

import re

from mika_shared.enums import Emotion

MAX_LOOKAHEAD = 40  # characters held back while looking for a tag

_EMOTIONS = {emotion.value for emotion in Emotion}
_CLOSERS = {"[": "]", "(": ")", "*": "*"}
_WORD = re.compile(r"[A-Za-z']+")

# Words that open a reply. After a bare emotion word ("Happy Ah, I'm ...") they show the word was a tag.
_REPLY_OPENERS = {
    "ah", "aw", "aww", "eh", "ehehe", "hehe", "haha", "hey", "hi", "hello", "hm", "hmm", "huh", "oh", "ohh",
    "ok", "okay", "oops", "so", "sure", "ugh", "uh", "um", "umm", "well", "wow", "yay", "yes", "no",
    "i", "i'm", "i've", "i'll", "it", "it's", "that", "that's", "this", "what", "thanks", "thank", "welcome",
}


class EmotionTagParser:
    """Feed the reply's text chunks in order; pass on what ``feed`` and ``finish`` return.

    ``emotion`` stays None until the parser has decided, which happens as soon as the tag (or its absence)
    is certain, usually with the first chunk or two.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._rest = ""
        self._at_start = True  # no text passed on yet: drop leading whitespace
        self.emotion: Emotion | None = None
        self.tag_found = False  # True only for a valid emotion tag
        self.raw_tag: str | None = None  # what the tag said, valid or not

    @property
    def decided(self) -> bool:
        return self.emotion is not None

    def feed(self, chunk: str) -> str:
        if self.decided:
            return self._pass(chunk)
        self._buffer += chunk
        return self._flush() if self._try_decide(final=False) else ""

    def finish(self) -> str:
        """Call at the end of the stream; returns any text still held back."""
        if self.decided:
            return ""
        self._try_decide(final=True)
        return self._flush()

    def _flush(self) -> str:
        rest, self._rest, self._buffer = self._rest, "", ""
        return self._pass(rest)

    def _pass(self, text: str) -> str:
        # Whitespace after the tag may arrive in a later chunk ("[happy]", " Hi"); drop it either way.
        if self._at_start:
            text = text.lstrip()
            self._at_start = not text
        return text

    def _resolve(self, tag: str | None, rest: str) -> bool:
        self.raw_tag = tag
        self.tag_found = tag in _EMOTIONS
        self.emotion = Emotion(tag) if self.tag_found else Emotion.NEUTRAL
        self._rest = rest.lstrip()
        return True

    def _no_tag(self, text: str) -> bool:
        self.emotion = Emotion.NEUTRAL
        self._rest = text
        return True

    def _try_decide(self, *, final: bool) -> bool:
        """Decide if possible. With final=True it always decides."""
        text = self._buffer.lstrip()
        if not text:
            return self._no_tag("") if final else False
        if len(text) > MAX_LOOKAHEAD:
            final = True  # held back long enough: whatever is still undecided is not a tag

        closer = _CLOSERS.get(text[0])
        if closer:
            end = text.find(closer, 1)
            if end == -1:
                return self._no_tag(text) if final else False
            inner = text[1:end].strip().lower()
            # Square brackets always mark a tag; (...) and *...* only when they hold an emotion.
            if text[0] == "[" or inner in _EMOTIONS:
                return self._resolve(inner, text[end + 1 :])
            return self._no_tag(text)

        word_match = _WORD.match(text)
        if not word_match:
            return self._no_tag(text)
        word = word_match.group(0).lower()
        after = text[word_match.end() :]
        if not after:
            # The word may still be growing ("Hap" -> "Happy") or need its next word.
            if not final and any(emotion.startswith(word) for emotion in _EMOTIONS):
                return False
            return self._no_tag(text)
        if word not in _EMOTIONS:
            return self._no_tag(text)
        return self._decide_bare_word(word, after, text, final)

    def _decide_bare_word(self, word: str, after: str, text: str, final: bool) -> bool:
        """A reply that starts with an emotion word: a leaked tag, or ordinary text like "Happy birthday"?"""
        if after[0] in ":|\n":
            return self._resolve(word, after[1:])
        if not after[0].isspace():
            return self._no_tag(text)  # "Happy!", "Happy,", "Happy-go-lucky"
        stripped = after.lstrip(" \t")
        if not stripped:
            return self._no_tag(text) if final else False
        if stripped[0] in ":|\n":
            return self._resolve(word, stripped[1:])
        if stripped[0] in "-–—":  # "Happy - Hi!", but not "Happy -ish"
            if len(stripped) == 1:
                return self._no_tag(text) if final else False
            return self._resolve(word, stripped[1:]) if stripped[1].isspace() else self._no_tag(text)
        next_match = _WORD.match(stripped)
        if not next_match:
            return self._no_tag(text)  # "Happy 2026!"
        if next_match.end() == len(stripped) and not final:
            return False  # the next word may not be complete yet
        if next_match.group(0).lower() in _REPLY_OPENERS:
            return self._resolve(word, stripped)
        return self._no_tag(text)
