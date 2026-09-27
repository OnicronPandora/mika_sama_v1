import json

import pytest
from pydantic import ValidationError

from mika_shared import events
from mika_shared.enums import (
    ClientComponent,
    ComponentState,
    Emotion,
    FilterAction,
    Intent,
    MessageSource,
    TranscriptRole,
)
from mika_shared.payloads import FilterResult, TurnResult, UserRequest

TURN = "3f2a9c1e5b7d4e0f8a6b2c9d1e3f5a7b"

# name -> (union, parser, the event types the implementation plan's section 5 lists for it)
CHANNELS = {
    "runtime_client": (
        events.RuntimeClientEvent,
        events.parse_runtime_client_event,
        {"user_message", "client_status"},
    ),
    "runtime_server": (
        events.RuntimeServerEvent,
        events.parse_runtime_server_event,
        {"turn_start", "sentence", "turn_end", "error"},
    ),
    "chat_client": (
        events.ChatClientEvent,
        events.parse_chat_client_event,
        {"admin_message", "playback_started", "playback_finished"},
    ),
    "chat_server": (
        events.ChatServerEvent,
        events.parse_chat_server_event,
        {"emotion", "audio_chunk", "turn_end", "transcript"},
    ),
}

SAMPLES = {
    "runtime_client": [
        events.UserMessage(user_id="admin", message="Hi Mika!", source=MessageSource.CHAT),
        events.ClientStatus(component=ClientComponent.TTS, status=ComponentState.READY),
    ],
    "runtime_server": [
        events.TurnStart(turn_id=TURN, emotion=Emotion.HAPPY),
        events.Sentence(turn_id=TURN, seq=0, text="Hi everyone!", action=FilterAction.ALLOW),
        events.TurnEnd(turn_id=TURN, last_seq=0, intent=Intent.CASUAL_CONVERSATION),
        events.TurnError(turn_id=TURN, message="LLM timed out"),
    ],
    "chat_client": [
        events.AdminMessage(message="How was your day?"),
        events.PlaybackStarted(turn_id=TURN, seq=0),
        events.PlaybackFinished(turn_id=TURN, seq=0),
    ],
    "chat_server": [
        events.EmotionUpdate(turn_id=TURN, emotion=Emotion.HAPPY),
        events.AudioChunk(turn_id=TURN, seq=0, text="Hi everyone!", audio_b64="UklGRg==", sample_rate=32000),
        events.ChatTurnEnd(turn_id=TURN, last_seq=0),
        events.Transcript(role=TranscriptRole.MIKA, text="Hi everyone!"),
    ],
}

ROUND_TRIPS = [(name, event) for name, samples in SAMPLES.items() for event in samples]


@pytest.mark.parametrize("name", CHANNELS)
def test_each_channel_carries_exactly_the_events_in_the_plan(name):
    union, _, planned = CHANNELS[name]
    assert {cls.model_fields["type"].default for cls in events.event_types(union)} == planned


@pytest.mark.parametrize("name", CHANNELS)
def test_samples_cover_every_event(name):
    union, _, _ = CHANNELS[name]
    assert {type(event) for event in SAMPLES[name]} == set(events.event_types(union))


@pytest.mark.parametrize(("name", "event"), ROUND_TRIPS, ids=[f"{n}:{e.type}" for n, e in ROUND_TRIPS])
def test_round_trip(name, event):
    raw = event.model_dump_json()
    assert json.loads(raw)["type"] == event.type
    parsed = CHANNELS[name][1](raw)
    assert type(parsed) is type(event)
    assert parsed == event


def test_parsers_reject_events_from_the_other_direction():
    with pytest.raises(ValidationError):
        events.parse_runtime_client_event(events.TurnStart(turn_id=TURN, emotion=Emotion.SAD).model_dump_json())
    with pytest.raises(ValidationError):
        events.parse_chat_client_event(events.Transcript(role=TranscriptRole.MIKA, text="Hi").model_dump_json())


def test_parsers_reject_unknown_types_and_bad_json():
    with pytest.raises(ValidationError):
        events.parse_chat_client_event('{"type": "hello"}')
    with pytest.raises(ValidationError):
        events.parse_chat_client_event("not json")


def test_same_type_name_on_two_channels_has_different_fields():
    runtime_end = events.parse_runtime_server_event(
        events.TurnEnd(turn_id=TURN, last_seq=2, intent=Intent.FILTER_INCIDENT).model_dump_json()
    )
    chat_end = events.parse_chat_server_event(events.ChatTurnEnd(turn_id=TURN, last_seq=2).model_dump_json())
    assert isinstance(runtime_end, events.TurnEnd)
    assert isinstance(chat_end, events.ChatTurnEnd)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        events.parse_chat_client_event('{"type": "admin_message", "message": "hi", "user_id": "someone"}')


def test_invalid_values_are_rejected():
    with pytest.raises(ValidationError):
        events.TurnStart(turn_id=TURN, emotion="excited")
    with pytest.raises(ValidationError):
        events.Sentence(turn_id=TURN, seq=-1, text="Hi", action=FilterAction.ALLOW)
    with pytest.raises(ValidationError):
        events.AdminMessage(message="   ")
    with pytest.raises(ValidationError):
        events.TurnStart(turn_id="not a valid id!", emotion=Emotion.HAPPY)
    with pytest.raises(ValidationError):
        events.AudioChunk(turn_id=TURN, seq=0, text="Hi", audio_b64="UklGRg==", sample_rate=0)


def test_message_text_is_trimmed():
    assert events.AdminMessage(message="  hello  ").message == "hello"


def test_turn_end_last_seq_is_required_but_nullable():
    empty_turn = events.TurnEnd(turn_id=TURN, last_seq=None, intent=Intent.ERROR_RECOVERY)
    assert json.loads(empty_turn.model_dump_json())["last_seq"] is None
    with pytest.raises(ValidationError):
        events.TurnEnd(turn_id=TURN, intent=Intent.CASUAL_CONVERSATION)


def test_error_without_a_turn():
    error = events.parse_runtime_server_event('{"type": "error", "message": "Server is shutting down"}')
    assert isinstance(error, events.TurnError)
    assert error.turn_id is None


def test_events_are_immutable():
    event = events.TurnStart(turn_id=TURN, emotion=Emotion.HAPPY)
    with pytest.raises(ValidationError):
        event.emotion = Emotion.SAD


def test_user_message_is_a_user_request():
    message = events.UserMessage(user_id="admin", message="Hi", source=MessageSource.VOICE)
    assert isinstance(message, UserRequest)


def test_enum_values_match_the_spec():
    assert [e.value for e in Emotion] == ["happy", "sad", "confused", "angry", "neutral"]
    assert [i.value for i in Intent] == ["casual_conversation", "filter_incident", "error_recovery"]
    assert [a.value for a in FilterAction] == ["ALLOW", "REPLACE", "BLOCK"]


@pytest.mark.parametrize(
    ("actions", "expected"),
    [
        ([], FilterAction.ALLOW),
        ([FilterAction.ALLOW, FilterAction.ALLOW], FilterAction.ALLOW),
        ([FilterAction.ALLOW, FilterAction.REPLACE], FilterAction.REPLACE),
        ([FilterAction.REPLACE, FilterAction.BLOCK, FilterAction.ALLOW], FilterAction.BLOCK),
    ],
)
def test_turn_action_is_the_most_severe(actions, expected):
    assert FilterAction.most_severe(actions) is expected


def test_filter_result_response_matches_action():
    assert FilterResult(action=FilterAction.ALLOW).filter_response is None
    assert FilterResult(action=FilterAction.BLOCK, filter_response="Let's talk about something else!", reason="word")
    with pytest.raises(ValidationError):
        FilterResult(action=FilterAction.ALLOW, filter_response="unexpected")
    with pytest.raises(ValidationError):
        FilterResult(action=FilterAction.REPLACE)
    with pytest.raises(ValidationError):
        FilterResult(action=FilterAction.BLOCK, filter_response="  ")


def test_turn_result_round_trip():
    result = TurnResult(
        intent=Intent.FILTER_INCIDENT,
        emotion=Emotion.CONFUSED,
        reply="Filtered. Let's talk about something else!",
        original_reply="[confused] Something unsafe.",
        action=FilterAction.REPLACE,
    )
    assert TurnResult.model_validate_json(result.model_dump_json()) == result
