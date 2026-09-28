"""Enumerations from the spec (docs/top_secret.md) and the event contracts."""

from collections.abc import Iterable
from enum import StrEnum


class Emotion(StrEnum):
    """Mika's emotion for one reply, read from the reply's leading [emotion] tag."""

    HAPPY = "happy"
    SAD = "sad"
    CONFUSED = "confused"
    ANGRY = "angry"
    NEUTRAL = "neutral"


class Intent(StrEnum):
    """Set by the system for each turn, never by the LLM."""

    CASUAL_CONVERSATION = "casual_conversation"
    FILTER_INCIDENT = "filter_incident"
    ERROR_RECOVERY = "error_recovery"


class FilterAction(StrEnum):
    """The output filter's verdict for one sentence."""

    ALLOW = "ALLOW"
    REPLACE = "REPLACE"
    BLOCK = "BLOCK"

    @classmethod
    def most_severe(cls, actions: Iterable["FilterAction"]) -> "FilterAction":
        """The action recorded for a whole turn: BLOCK over REPLACE over ALLOW."""
        order = (cls.ALLOW, cls.REPLACE, cls.BLOCK)
        return max(actions, key=order.index, default=cls.ALLOW)


class MessageSource(StrEnum):
    """Where a user message came from."""

    CHAT = "chat"
    VOICE = "voice"


class TranscriptRole(StrEnum):
    """Who said a transcript line."""

    ADMIN = "admin"
    MIKA = "mika"


class ClientComponent(StrEnum):
    """A part of the Acer side that reports its health to the Mac."""

    TTS = "tts"
    STT = "stt"
    AVATAR_PAGE = "avatar_page"
    ADMIN_PAGE = "admin_page"


class ComponentState(StrEnum):
    """Health of one client component."""

    STARTING = "starting"
    READY = "ready"
    ERROR = "error"
    STOPPED = "stopped"
