"""/ws/chat: the browser pages' connection to the Acer (plan, section 5.2).

A page says which one it is in the URL: /ws/chat?page=avatar (the Live2D page, in OBS or Chrome) or
/ws/chat?page=admin (the chatbox). Avatar pages get the emotion, audio chunks and turn_end, and report
playback; admin pages send typed messages and get the transcript. Several pages of each kind may be open.

Pages run on this machine, served by the Vite dev server, so the client listens on 127.0.0.1 only, and
browser origins other than ClientSettings.allowed_origins are refused (CORS doesn't cover WebSockets).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from enum import StrEnum

from fastapi import APIRouter, WebSocket, status
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from mika_shared.events import ChatClientEvent, ChatServerEvent, parse_chat_client_event

log = logging.getLogger(__name__)

router = APIRouter()


class Page(StrEnum):
    AVATAR = "avatar"
    ADMIN = "admin"


@router.websocket("/ws/chat")
async def chat(websocket: WebSocket) -> None:
    services = websocket.app.state.services
    origin = websocket.headers.get("origin")
    if not origin_allowed(origin, services.settings.allowed_origins):
        log.warning("Refused a /ws/chat connection from origin %r", origin)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        page = Page(websocket.query_params.get("page", ""))
    except ValueError:
        log.warning("Refused a /ws/chat connection without ?page=avatar or ?page=admin")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    await services.pages.serve(page, websocket)


def origin_allowed(origin: str | None, allowed: Collection[str]) -> bool:
    """Browsers always send Origin; a client that isn't a browser sends none."""
    return origin is None or origin in allowed


class _Connection:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.lock = asyncio.Lock()


class PageHub:
    """The pages connected to /ws/chat. on_event, on_opened and on_closed are set by the Relay."""

    def __init__(self, *, send_timeout: float) -> None:
        self._send_timeout = send_timeout
        self._pages: dict[Page, set[_Connection]] = {page: set() for page in Page}
        self.on_event: Callable[[Page, ChatClientEvent], Awaitable[None]] | None = None
        self.on_opened: Callable[[Page], Awaitable[None]] | None = None
        self.on_closed: Callable[[Page], Awaitable[None]] | None = None

    def count(self, page: Page) -> int:
        return len(self._pages[page])

    async def to_avatar(self, event: ChatServerEvent) -> None:
        await self._broadcast(Page.AVATAR, event)

    async def to_admin(self, event: ChatServerEvent) -> None:
        await self._broadcast(Page.ADMIN, event)

    async def serve(self, page: Page, websocket: WebSocket) -> None:
        """Read the page's events until it disconnects."""
        connection = _Connection(websocket)
        self._pages[page].add(connection)
        log.info("%s page connected (%d open)", page.value, self.count(page))
        try:
            if self.on_opened:
                await self.on_opened(page)
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                data = message.get("text")
                if data is None:
                    data = message.get("bytes") or b""
                try:
                    event = parse_chat_client_event(data)
                except ValidationError as e:
                    log.warning("Invalid event from the %s page: %s", page.value, e.errors(include_url=False)[0]["msg"])
                    continue
                if self.on_event:
                    await self.on_event(page, event)
        finally:
            self._pages[page].discard(connection)
            log.info("%s page disconnected (%d open)", page.value, self.count(page))
            if self.on_closed:
                await self.on_closed(page)

    async def _broadcast(self, page: Page, event: ChatServerEvent) -> None:
        data = event.model_dump_json()
        for connection in list(self._pages[page]):
            try:
                async with asyncio.timeout(self._send_timeout):
                    async with connection.lock:
                        await connection.websocket.send_text(data)
            except (WebSocketDisconnect, OSError, RuntimeError, TimeoutError):
                log.warning("A %s page stopped receiving; dropping it", page.value)
                self._pages[page].discard(connection)
