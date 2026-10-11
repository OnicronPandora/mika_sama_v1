"""One turn on the Mac, from a user's message to Mika's approved sentences (plan, section 6).

    user_message -> prompt (personality, history window, memories) -> Ollama stream -> emotion -> turn_start
                 -> sentences -> output filter, in order -> sentence events -> turn_end
                 -> chat_logs, memories, recent turns -> warm Ollama up for the user's next turn

The 8 GB Mac's Ollama serves one request at a time (Spike A), so the whole reply is generated before the
filter's calls start: sent earlier, they would only wait in Ollama's queue, with their timeouts counting the
wait. The emotion is sent as soon as it is known, so the avatar reacts while the reply is generated.

Failures are contained: a reply that breaks off still sends the sentences it completed, and memory can fail
without stopping the turn. Only ClientGone (the Acer can't be reached) and cancellation stop a turn early, and
CancelledError always propagates.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass, field, replace
from uuid import uuid4

from mika_shared.enums import Emotion, FilterAction
from mika_shared.events import RuntimeServerEvent, Sentence, TurnEnd, TurnError, TurnStart, UserMessage
from mika_shared.payloads import ADMIN_USER_ID, TurnResult

from ..config import Settings
from ..filter.context import TurnContext
from ..filter.policy import OutputFilter
from ..llm.engine import LLMEngine
from ..llm.streaming import EmotionDecided, reply_events
from ..memory.archive import TurnRecord
from ..memory.conversation import Conversation
from ..memory.history import history_messages, history_text
from ..memory.prompt import build_turn_messages, prefix_messages
from ..memory.rag import memories_block
from ..state.manager import StateManager
from .intent import decide_intent

log = logging.getLogger(__name__)

Send = Callable[[RuntimeServerEvent], Awaitable[None]]

FAILED_MESSAGE = "Mika couldn't answer this time (details in server.log)."


class ClientGone(Exception):
    """The Acer can't be reached: the turn stops, and nothing more is sent or saved."""


@dataclass
class _Reply:
    """What a turn has produced so far."""

    turn_id: str
    emotion: Emotion = Emotion.NEUTRAL
    raw: list[str] = field(default_factory=list)  # the LLM's output as streamed (original_reply)
    sentences: list[str] = field(default_factory=list)  # from the chunker, before filtering
    spoken: list[str] = field(default_factory=list)  # what was sent to the Acer, after filtering
    actions: list[FilterAction] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    failed: bool = False
    first_sentence_after: float | None = None  # seconds from the user's message


class TurnRunner:
    def __init__(
        self,
        *,
        engine: LLMEngine,
        output_filter: OutputFilter,
        conversation: Conversation,
        state: StateManager,
        system_prompt: str,
        assistant: str,
        settings: Settings,
    ) -> None:
        self.conversation = conversation
        self.system_prompt = system_prompt
        self._engine = engine
        self._output_filter = output_filter
        self._state = state
        self._assistant = assistant  # Mika's name in the filter's context
        self._settings = settings

    def speaker(self, user_id: str) -> str:
        """How the user is named in memories and in the filter's context."""
        return self._settings.memory.admin_name if user_id == ADMIN_USER_ID else user_id

    async def run(self, request: UserMessage, send: Send) -> TurnResult:
        reply = _Reply(turn_id=uuid4().hex)
        log.info("Turn %s: %s (%s): %r", reply.turn_id, self.speaker(request.user_id), request.source.value, request.message)
        try:
            return await self._run(request, reply, send)
        except asyncio.CancelledError:
            log.info("Turn %s: cancelled (the Acer left, or the server is shutting down)", reply.turn_id)
            raise
        except ClientGone:
            log.info("Turn %s: stopped, the Acer can't be reached", reply.turn_id)
            raise

    async def _run(self, request: UserMessage, reply: _Reply, send: Send) -> TurnResult:
        started = time.perf_counter()
        speaker = self.speaker(request.user_id)
        history = await self.conversation.window(request.user_id)
        recalled = await self.conversation.recall(request.message, history)
        memories = memories_block(recalled, self._settings.memory.memory_max_tokens)
        prompt = build_turn_messages(
            system_prompt=self.system_prompt,
            history=history_messages(history),
            memories=memories,
            user_message=request.message,
            num_predict=self._settings.llm.num_predict,
        )
        context = TurnContext(
            user_message=request.message,
            history=history_text(
                history,
                speaker=speaker,
                assistant=self._assistant,
                max_turns=self._settings.memory.classifier_history_turns,
            ),
        )

        await self._generate(reply, prompt, send)
        await self._check_and_send(reply, context, send, started)

        intent = decide_intent(reply.actions, failed=reply.failed)
        if reply.failed and not reply.spoken:
            await send(TurnError(turn_id=reply.turn_id, message=FAILED_MESSAGE))
        else:
            last_seq = len(reply.spoken) - 1 if reply.spoken else None
            await send(TurnEnd(turn_id=reply.turn_id, last_seq=last_seq, intent=intent))
        first = f"{reply.first_sentence_after:.1f} s" if reply.first_sentence_after is not None else "-"
        log.info(
            "Turn %s: %s, %d sentence(s) %s, %s; first sentence after %s, turn end after %.1f s",
            reply.turn_id,
            reply.emotion.value,
            len(reply.spoken),
            "/".join(action.value for action in reply.actions) or "-",
            intent.value,
            first,
            time.perf_counter() - started,
        )

        result = TurnResult(
            intent=intent,
            emotion=reply.emotion,
            reply=" ".join(reply.spoken),
            original_reply="".join(reply.raw),
            action=FilterAction.most_severe(reply.actions),
        )
        await self.conversation.record(
            TurnRecord(
                session_id=self._state.state.session_id,
                user_id=request.user_id,
                speaker=speaker,
                user_message=request.message,
                result=result,
                rag_context_used=memories,
                filter_reason="; ".join(reply.reasons) or None,
            )
        )
        await self.prewarm(request.user_id)
        return result

    async def prefix(self, user_id: str) -> list[dict[str, str]]:
        """What the user's next prompt starts with: the system prompt and their history window."""
        history = await self.conversation.window(user_id)
        return prefix_messages(system_prompt=self.system_prompt, history=history_messages(history))

    async def prewarm(self, user_id: str) -> None:
        """Have Ollama read the start of the user's next prompt now, while Mika is still speaking."""
        try:
            async with asyncio.timeout(self._settings.llm.warm_up_timeout):
                await self._engine.warm_up(await self.prefix(user_id), label="prewarm")
        except Exception:
            log.warning("Warming Ollama up for the next turn failed", exc_info=True)

    async def _generate(self, reply: _Reply, prompt: list[dict[str, str]], send: Send) -> None:
        """Stream Mika's reply: send turn_start as soon as the emotion is known, and collect the sentences."""
        try:
            async with asyncio.timeout(self._settings.llm.reply_timeout):
                async with aclosing(self._engine.stream_chat(prompt, label="reply")) as tokens:
                    async for event in reply_events(_recorded(tokens, reply.raw)):
                        if isinstance(event, EmotionDecided):
                            reply.emotion = event.emotion
                            self._state.set_emotion(event.emotion)
                            await send(TurnStart(turn_id=reply.turn_id, emotion=event.emotion))
                        else:
                            reply.sentences.append(event.text)
        except ClientGone:
            raise
        except Exception:  # Ollama down, timed out... (CancelledError is not an Exception: it propagates)
            log.exception(
                "Turn %s: the reply failed after %d complete sentence(s)", reply.turn_id, len(reply.sentences)
            )
            reply.failed = True

    async def _check_and_send(self, reply: _Reply, context: TurnContext, send: Send, started: float) -> None:
        """Run each sentence through the output filter, in order, and send what Mika says instead.

        Nothing unchecked is ever sent: if the filter itself breaks, the rest of the reply is dropped.
        """
        for sentence in reply.sentences:
            check_context = replace(context, reply_so_far=" ".join(reply.spoken))
            try:
                result = await self._output_filter.check(sentence, check_context)
            except Exception:
                log.exception("Turn %s: the output filter failed; the rest of the reply is dropped", reply.turn_id)
                reply.failed = True
                return
            text = sentence if result.action is FilterAction.ALLOW else result.filter_response
            if result.action is not FilterAction.ALLOW:
                log.info("Turn %s: %s %r -> %r (%s)", reply.turn_id, result.action.value, sentence, text, result.reason)
            reply.spoken.append(text)
            reply.actions.append(result.action)
            if result.reason:
                reply.reasons.append(result.reason)
            if reply.first_sentence_after is None:
                reply.first_sentence_after = time.perf_counter() - started
            await send(Sentence(turn_id=reply.turn_id, seq=len(reply.spoken) - 1, text=text, action=result.action))


async def _recorded(tokens: AsyncIterable[str], raw: list[str]) -> AsyncIterator[str]:
    async for token in tokens:
        raw.append(token)
        yield token
