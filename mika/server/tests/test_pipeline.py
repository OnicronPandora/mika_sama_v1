"""One turn end to end with a scripted LLM and an in-memory archive (plan, section 6)."""

import asyncio
import random

import pytest
from fakes import HANG, FakeEngine, fake_settings, is_prompt_prefix, verdict

from app.filter.ai_classifier import FilterPolicy, SafetyClassifier
from app.filter.hard_rules import ProhibitedWords
from app.filter.policy import OutputFilter
from app.filter.replacer import Replacer
from app.memory.archive import MemoryArchive
from app.memory.conversation import Conversation
from app.personality.engine import Personality
from app.state.manager import StateManager
from app.turn.pipeline import FAILED_MESSAGE, ClientGone, TurnRunner
from mika_shared.enums import Emotion, FilterAction, Intent, MessageSource
from mika_shared.events import Sentence, TurnEnd, TurnError, TurnStart, UserMessage
from mika_shared.payloads import TurnResult

SYSTEM = "You are Mika-sama."
FALLBACK = "Let's talk about something else!"
MOCHI = "Pandora: I adopted a cat named Mochi.\nMika-sama: Mochi is adorable!"


class Turns:
    """A TurnRunner with a scripted LLM and an in-memory archive, and the events of its last turn."""

    def __init__(self, engine: FakeEngine, *, words=(), archive=None, reply_timeout=60.0) -> None:
        self.engine = engine
        self.archive = archive or MemoryArchive()
        self.settings = fake_settings(reply_timeout=reply_timeout)
        self.state = StateManager(Personality(name="Mika-sama", role="AI VTuber", core_identity=SYSTEM, guidelines=[]))
        self.events: list = []
        output_filter = OutputFilter(
            words=ProhibitedWords(list(words)),
            classifier=SafetyClassifier(engine, FilterPolicy(allowed=["a"], unsafe=["b"]), self.settings.filter, streamer="Mika-sama"),
            replacer=Replacer(engine, self.settings.filter, persona="Mika-sama, AI VTuber"),
            fallbacks=[FALLBACK],
            filtered_prefix="Filtered!",
            rng=random.Random(0),
        )
        self.runner = TurnRunner(
            engine=engine,
            output_filter=output_filter,
            conversation=Conversation(self.archive, self.settings.memory),
            state=self.state,
            system_prompt=SYSTEM,
            assistant="Mika-sama",
            settings=self.settings,
        )

    async def send(self, event) -> None:
        self.events.append(event)

    async def say(self, message: str, user_id: str = "admin") -> TurnResult:
        self.events = []
        request = UserMessage(user_id=user_id, message=message, source=MessageSource.CHAT)
        return await self.runner.run(request, self.send)

    @property
    def turn_id(self) -> str:
        return self.events[0].turn_id


async def test_a_full_turn():
    engine = FakeEngine(verdict(True), verdict(True), replies=[["[hap", "py] Hi Pan", "dora! How was", " your day?"]])
    turns = Turns(engine)
    result = await turns.say("Hi Mika!")
    turn_id = turns.turn_id
    assert turns.events == [
        TurnStart(turn_id=turn_id, emotion=Emotion.HAPPY),
        Sentence(turn_id=turn_id, seq=0, text="Hi Pandora!", action=FilterAction.ALLOW),
        Sentence(turn_id=turn_id, seq=1, text="How was your day?", action=FilterAction.ALLOW),
        TurnEnd(turn_id=turn_id, last_seq=1, intent=Intent.CASUAL_CONVERSATION),
    ]
    assert result == TurnResult(
        intent=Intent.CASUAL_CONVERSATION,
        emotion=Emotion.HAPPY,
        reply="Hi Pandora! How was your day?",
        original_reply="[happy] Hi Pandora! How was your day?",
        action=FilterAction.ALLOW,
    )
    (record,) = turns.archive.records
    assert (record.user_id, record.speaker, record.user_message, record.result) == ("admin", "Pandora", "Hi Mika!", result)
    assert (record.session_id, record.rag_context_used, record.filter_reason) == (turns.state.state.session_id, None, None)
    assert turns.state.state.current_emotion is Emotion.HAPPY
    assert engine.streams == [[{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Hi Mika!"}]]
    # Then Ollama reads the start of the next prompt, while Mika is still speaking.
    assert engine.warm_ups == [
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Hi Mika!"},
            {"role": "assistant", "content": "[happy] Hi Pandora! How was your day?"},
        ]
    ]


async def test_the_next_turn_sees_the_last_one_and_recalled_memories():
    engine = FakeEngine(verdict(True), verdict(True), replies=[["[happy] Hi!"], ["[happy] Mochi is great!"]])
    archive = MemoryArchive(recall=lambda query: [MOCHI] if "Mochi" in query else [])
    turns = Turns(engine, archive=archive)
    await turns.say("Hi Mika!")
    await turns.say("How is Mochi?")
    prompt = engine.streams[1]
    memories = "[Things you remember from earlier conversations (they may be old):\n- " + MOCHI.replace("\n", " / ") + "]"
    assert prompt == [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Hi Mika!"},
        {"role": "assistant", "content": "[happy] Hi!"},
        {"role": "user", "content": memories + "\n\nHow is Mochi?"},
    ]
    assert is_prompt_prefix(engine.warm_ups[0], prompt)  # the warm-up after turn 1 started turn 2's prompt
    assert archive.records[1].rag_context_used == memories


async def test_filtered_sentences_are_replaced_in_order():
    engine = FakeEngine(
        verdict(True), verdict(False, "threat"), "Anyway, games?", verdict(True), verdict(True),
        replies=[["[angry] Fine. I will hurt you. Bye."]],
    )  # fmt: skip
    turns = Turns(engine)
    result = await turns.say("Say something mean.")
    turn_id = turns.turn_id
    assert turns.events == [
        TurnStart(turn_id=turn_id, emotion=Emotion.ANGRY),
        Sentence(turn_id=turn_id, seq=0, text="Fine.", action=FilterAction.ALLOW),
        Sentence(turn_id=turn_id, seq=1, text="Filtered! Anyway, games?", action=FilterAction.REPLACE),
        Sentence(turn_id=turn_id, seq=2, text="Bye.", action=FilterAction.ALLOW),
        TurnEnd(turn_id=turn_id, last_seq=2, intent=Intent.FILTER_INCIDENT),
    ]
    assert (result.reply, result.original_reply) == ("Fine. Filtered! Anyway, games? Bye.", "[angry] Fine. I will hurt you. Bye.")
    assert result.action is FilterAction.REPLACE
    assert turns.archive.records[0].filter_reason == "classifier: threat"
    # The filter sees what Mika actually said, not what she first wrote.
    last_check = engine.classifier_calls[-1].messages[1]["content"]
    assert "Said so far in this reply: Fine. Filtered! Anyway, games?\n" in last_check


async def test_a_blocked_sentence_is_rewritten():
    engine = FakeEngine("Let's keep it friendly!", verdict(True), verdict(True), replies=[["[happy] Oh darn it. Okay!"]])
    turns = Turns(engine, words=["darn"])
    result = await turns.say("Hi!")
    assert [(e.text, e.action) for e in turns.events if isinstance(e, Sentence)] == [
        ("Let's keep it friendly!", FilterAction.BLOCK),
        ("Okay!", FilterAction.ALLOW),
    ]
    assert (result.action, result.intent) == (FilterAction.BLOCK, Intent.FILTER_INCIDENT)
    assert turns.archive.records[0].filter_reason == "prohibited word: darn"


async def test_when_ollama_is_down_the_acer_gets_an_error():
    engine = FakeEngine(verdict(True), replies=[ConnectionError("Ollama is down"), ["[happy] Back!"]])
    turns = Turns(engine)
    result = await turns.say("Hi Mika!")
    assert turns.events == [TurnError(turn_id=turns.turn_id, message=FAILED_MESSAGE)]
    assert (result.intent, result.reply, result.original_reply) == (Intent.ERROR_RECOVERY, "", "")
    assert turns.archive.records[0].result == result  # logged...
    await turns.say("Are you there?")
    assert engine.streams[1] == [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Are you there?"}]
    # ...but not part of the conversation


async def test_a_reply_that_breaks_off_keeps_its_complete_sentences():
    engine = FakeEngine(verdict(True), replies=[["[sad] One. Two", ConnectionError("lost")]])
    turns = Turns(engine)
    result = await turns.say("Count!")
    assert [type(e) for e in turns.events] == [TurnStart, Sentence, TurnEnd]
    assert turns.events[1].text == "One."
    assert turns.events[2] == TurnEnd(turn_id=turns.turn_id, last_seq=0, intent=Intent.ERROR_RECOVERY)
    assert (result.reply, result.original_reply) == ("One.", "[sad] One. Two")


async def test_a_stalled_reply_times_out_and_its_stream_is_closed():
    engine = FakeEngine(replies=[["[happy] Hi", HANG]])
    turns = Turns(engine, reply_timeout=0.1)
    await turns.say("Hi!")
    assert turns.events == [
        TurnStart(turn_id=turns.turn_id, emotion=Emotion.HAPPY),
        TurnError(turn_id=turns.turn_id, message=FAILED_MESSAGE),
    ]
    assert engine.open_streams == 0


async def test_an_empty_reply_ends_the_turn_without_sentences():
    engine = FakeEngine(replies=[["[confused]"]])
    turns = Turns(engine)
    result = await turns.say("Hm?")
    assert turns.events == [
        TurnStart(turn_id=turns.turn_id, emotion=Emotion.CONFUSED),
        TurnEnd(turn_id=turns.turn_id, last_seq=None, intent=Intent.CASUAL_CONVERSATION),
    ]
    assert result.reply == ""


async def test_the_turn_stops_when_the_acer_is_gone():
    engine = FakeEngine(verdict(True), verdict(True), replies=[["[happy] One. Two."]])
    turns = Turns(engine)

    async def send(event):
        if isinstance(event, Sentence):
            raise ClientGone("the Acer disconnected")
        turns.events.append(event)

    with pytest.raises(ClientGone):
        await turns.runner.run(UserMessage(user_id="admin", message="Hi!", source=MessageSource.CHAT), send)
    assert len(engine.calls) == 1  # no more filter calls after the failed send
    assert turns.archive.records == [] and engine.warm_ups == []


async def test_cancelling_a_turn_closes_the_reply_stream():
    engine = FakeEngine(replies=[["[happy] Hi", HANG]])
    turns = Turns(engine)
    task = asyncio.create_task(turns.say("Hi!"))
    while not turns.events:  # turn_start: the emotion is sent while the reply is still being generated
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.open_streams == 0
    assert turns.archive.records == []


async def test_nothing_unchecked_is_sent_when_the_filter_breaks():
    engine = FakeEngine(verdict(True), replies=[["[happy] One. Two."]])
    turns = Turns(engine)
    check = turns.runner._output_filter.check

    async def broken_on_the_second(sentence, context):
        if sentence == "Two.":
            raise RuntimeError("bug")
        return await check(sentence, context)

    turns.runner._output_filter.check = broken_on_the_second
    result = await turns.say("Count!")
    assert [getattr(e, "text", None) for e in turns.events] == [None, "One.", None]
    assert turns.events[-1] == TurnEnd(turn_id=turns.turn_id, last_seq=0, intent=Intent.ERROR_RECOVERY)
    assert result.reply == "One."
