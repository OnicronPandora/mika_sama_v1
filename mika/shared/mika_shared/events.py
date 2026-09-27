"""WebSocket events (implementation plan, section 5).

Every event is JSON with a ``type`` field. Each channel direction has its own union and parser:

- /ws/runtime, Acer -> Mac: RuntimeClientEvent, parse_runtime_client_event
- /ws/runtime, Mac -> Acer: RuntimeServerEvent, parse_runtime_server_event
- /ws/chat, browser -> Acer: ChatClientEvent, parse_chat_client_event
- /ws/chat, Acer -> browser: ChatServerEvent, parse_chat_server_event

Send an event with ``event.model_dump_json()``. The parsers raise ``pydantic.ValidationError`` for anything
that is not a valid event for that direction.
"""

import typing
from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt, PositiveInt, TypeAdapter

from .base import Contract, NonEmptyStr, TurnId
from .enums import ClientComponent, ComponentState, Emotion, FilterAction, Intent, MessageSource, TranscriptRole
from .payloads import UserRequest

_SEQ = "0-based position of the sentence in the spoken order."
_LAST_SEQ = "seq of the turn's last sentence; null when the turn produced no sentences."

# ---- /ws/runtime: Acer -> Mac ----


class UserMessage(UserRequest):
    """The only request payload. Admin input (chatbox and voice) uses user_id "admin"."""

    type: Literal["user_message"] = "user_message"
    source: MessageSource


class ClientStatus(Contract):
    """Health update from the Acer: TTS ready, STT ready, avatar page connected, and so on."""

    type: Literal["client_status"] = "client_status"
    component: ClientComponent
    status: ComponentState
    detail: str | None = None


# ---- /ws/runtime: Mac -> Acer ----


class TurnStart(Contract):
    """Sent as soon as the reply's emotion tag is parsed. The Acer mutes STT and forwards the emotion."""

    type: Literal["turn_start"] = "turn_start"
    turn_id: TurnId
    emotion: Emotion


class Sentence(Contract):
    """One approved sentence, sent in spoken order."""

    type: Literal["sentence"] = "sentence"
    turn_id: TurnId
    seq: NonNegativeInt = Field(description=_SEQ)
    text: NonEmptyStr
    action: FilterAction


class TurnEnd(Contract):
    """No more sentences for this turn."""

    type: Literal["turn_end"] = "turn_end"
    turn_id: TurnId
    last_seq: NonNegativeInt | None = Field(description=_LAST_SEQ)
    intent: Intent


class TurnError(Contract):
    """The turn failed. The Acer unmutes STT."""

    type: Literal["error"] = "error"
    turn_id: TurnId | None = Field(default=None, description="null when the error is not tied to a turn.")
    message: NonEmptyStr


# ---- /ws/chat: browser -> Acer ----


class AdminMessage(Contract):
    """Typed in the admin chatbox. The Acer forwards it as a user_message with user_id "admin"."""

    type: Literal["admin_message"] = "admin_message"
    message: NonEmptyStr


class PlaybackStarted(Contract):
    """The avatar page started playing a sentence's audio."""

    type: Literal["playback_started"] = "playback_started"
    turn_id: TurnId
    seq: NonNegativeInt = Field(description=_SEQ)


class PlaybackFinished(Contract):
    """The avatar page finished a sentence's audio. At the turn's last_seq, the Acer unmutes STT."""

    type: Literal["playback_finished"] = "playback_finished"
    turn_id: TurnId
    seq: NonNegativeInt = Field(description=_SEQ)


# ---- /ws/chat: Acer -> browser ----


class EmotionUpdate(Contract):
    """Switch the avatar's expression for this turn."""

    type: Literal["emotion"] = "emotion"
    turn_id: TurnId
    emotion: Emotion


class AudioChunk(Contract):
    """One spoken sentence: its audio and its transcript line."""

    type: Literal["audio_chunk"] = "audio_chunk"
    turn_id: TurnId
    seq: NonNegativeInt = Field(description=_SEQ)
    text: NonEmptyStr
    audio_b64: NonEmptyStr = Field(description="A complete WAV file, base64-encoded.")
    sample_rate: PositiveInt


class ChatTurnEnd(Contract):
    """Tells the avatar page that the reply is complete."""

    type: Literal["turn_end"] = "turn_end"
    turn_id: TurnId
    last_seq: NonNegativeInt | None = Field(description=_LAST_SEQ)


class Transcript(Contract):
    """One line for the admin page's chat log."""

    type: Literal["transcript"] = "transcript"
    role: TranscriptRole
    text: NonEmptyStr


# ---- One union per channel direction ----

RuntimeClientEvent = Annotated[UserMessage | ClientStatus, Field(discriminator="type")]
RuntimeServerEvent = Annotated[TurnStart | Sentence | TurnEnd | TurnError, Field(discriminator="type")]
ChatClientEvent = Annotated[AdminMessage | PlaybackStarted | PlaybackFinished, Field(discriminator="type")]
ChatServerEvent = Annotated[EmotionUpdate | AudioChunk | ChatTurnEnd | Transcript, Field(discriminator="type")]

_runtime_client = TypeAdapter(RuntimeClientEvent)
_runtime_server = TypeAdapter(RuntimeServerEvent)
_chat_client = TypeAdapter(ChatClientEvent)
_chat_server = TypeAdapter(ChatServerEvent)


def parse_runtime_client_event(data: str | bytes) -> UserMessage | ClientStatus:
    """Parse a /ws/runtime message sent by the Acer."""
    return _runtime_client.validate_json(data)


def parse_runtime_server_event(data: str | bytes) -> TurnStart | Sentence | TurnEnd | TurnError:
    """Parse a /ws/runtime message sent by the Mac."""
    return _runtime_server.validate_json(data)


def parse_chat_client_event(data: str | bytes) -> AdminMessage | PlaybackStarted | PlaybackFinished:
    """Parse a /ws/chat message sent by a browser page."""
    return _chat_client.validate_json(data)


def parse_chat_server_event(data: str | bytes) -> EmotionUpdate | AudioChunk | ChatTurnEnd | Transcript:
    """Parse a /ws/chat message sent by the Acer."""
    return _chat_server.validate_json(data)


def event_types(union: object) -> tuple[type[Contract], ...]:
    """The event classes in one of the channel unions above, in declaration order."""
    return typing.get_args(typing.get_args(union)[0])
