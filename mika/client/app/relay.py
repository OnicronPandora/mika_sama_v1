"""The Acer's routing between the Mac (/ws/runtime), the browser pages (/ws/chat), Mika's voice and the mic.

The Acer makes no decisions about the conversation (spec: it is I/O only). It forwards what Pandora types or
says to the Mac as the admin, speaks what the Mac approves, keeps the mic muted while Mika answers, and tells
the Mac how its parts are doing (client_status).
"""

import logging
from collections.abc import Awaitable, Callable

from mika_shared.enums import ClientComponent, ComponentState, MessageSource, TranscriptRole
from mika_shared.events import (
    AdminMessage,
    ChatClientEvent,
    ClientStatus,
    Notice,
    PlaybackFinished,
    RuntimeClientEvent,
    RuntimeServerEvent,
    Sentence,
    Transcript,
    TurnEnd,
    TurnError,
    TurnStart,
    UserMessage,
)
from mika_shared.payloads import ADMIN_USER_ID

from .api.ws_chat import Page, PageHub
from .stt.gate import HalfDuplexGate
from .tts.speaker import Speaker

log = logging.getLogger(__name__)

PAGE_COMPONENTS = {Page.AVATAR: ClientComponent.AVATAR_PAGE, Page.ADMIN: ClientComponent.ADMIN_PAGE}
UNREACHABLE = "The Mac isn't reachable, so Mika didn't get that message."


class Relay:
    def __init__(
        self,
        *,
        send_to_mac: Callable[[RuntimeClientEvent], Awaitable[bool]],
        pages: PageHub,
        speaker: Speaker,
        gate: HalfDuplexGate,
        playback_margin: float,
    ) -> None:
        self._send_to_mac = send_to_mac
        self._pages = pages
        self._speaker = speaker
        self._gate = gate
        self._playback_margin = playback_margin
        self._statuses: dict[ClientComponent, ClientStatus] = {}
        self._open_turns: dict[str, int | None] = {}  # turns in progress: the last seq given to the speaker
        pages.on_event, pages.on_opened, pages.on_closed = self.on_page_event, self.on_page_opened, self.on_page_closed

    async def user_said(self, text: str, source: MessageSource) -> bool:
        """Pandora typed or said something: it goes to the Mac, and the mic stays muted until Mika has answered."""
        if not await self._send_to_mac(UserMessage(user_id=ADMIN_USER_ID, message=text, source=source)):
            log.warning("The Mac isn't reachable; %s message dropped: %r", source.value, text)
            await self._pages.to_admin(Notice(text=UNREACHABLE))
            return False
        self._gate.message_sent()
        log.info("Pandora (%s): %r", source.value, text)
        await self._pages.to_admin(Transcript(role=TranscriptRole.ADMIN, text=text))
        return True

    @property
    def statuses(self) -> dict[ClientComponent, ComponentState]:
        return {component: status.status for component, status in self._statuses.items()}

    async def set_status(self, component: ClientComponent, state: ComponentState, detail: str | None = None) -> None:
        status = ClientStatus(component=component, status=state, detail=detail)
        self._statuses[component] = status
        await self._send_to_mac(status)

    # ---- the Mac

    async def on_mac_event(self, event: RuntimeServerEvent) -> None:
        if isinstance(event, TurnStart):
            self._gate.turn_started(event.turn_id)
            self._open_turns[event.turn_id] = None
            self._speaker.emotion(event.turn_id, event.emotion)
        elif isinstance(event, Sentence):
            self._open_turns[event.turn_id] = event.seq
            self._speaker.say(event.turn_id, event.seq, event.text)
            await self._pages.to_admin(Transcript(role=TranscriptRole.MIKA, text=event.text))
        elif isinstance(event, TurnEnd):
            self._open_turns.pop(event.turn_id, None)
            self._speaker.end(event.turn_id, event.last_seq)
        elif isinstance(event, TurnError):
            log.warning("The Mac: %s (turn %s)", event.message, event.turn_id)
            await self._pages.to_admin(Notice(text=event.message))
            if event.turn_id is None:  # a message refused (busy, shutting down)
                self._gate.message_refused()
            elif event.turn_id in self._open_turns:  # the turn had started: the avatar page has its emotion
                self._open_turns.pop(event.turn_id)
                self._speaker.end(event.turn_id, None)
            else:
                self._gate.turn_failed(event.turn_id)

    async def on_mac_connected(self) -> None:
        for status in list(self._statuses.values()):
            await self._send_to_mac(status)

    async def on_mac_disconnected(self) -> None:
        # The Mac cancels a turn when its connection closes: the page plays what it has, and nothing more comes.
        for turn_id, last_seq in self._open_turns.items():
            self._speaker.end(turn_id, last_seq)
        self._open_turns.clear()
        self._gate.reset()

    def on_spoken(self, turn_id: str, last_seq: int | None, audio_seconds: float) -> None:
        """From the speaker: the turn's audio has all gone to the avatar pages."""
        wait = audio_seconds + self._playback_margin if self._pages.count(Page.AVATAR) else None
        self._gate.turn_spoken(turn_id, last_seq, wait=wait)

    # ---- the pages

    async def on_page_event(self, page: Page, event: ChatClientEvent) -> None:
        if isinstance(event, AdminMessage):
            await self.user_said(event.message, MessageSource.CHAT)
        elif isinstance(event, PlaybackFinished):
            self._gate.playback_finished(event.turn_id, event.seq)

    async def on_page_opened(self, page: Page) -> None:
        if self._pages.count(page) == 1:
            await self.set_status(PAGE_COMPONENTS[page], ComponentState.READY)

    async def on_page_closed(self, page: Page) -> None:
        if self._pages.count(page) == 0:
            await self.set_status(PAGE_COMPONENTS[page], ComponentState.STOPPED)
