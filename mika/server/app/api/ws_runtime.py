"""/ws/runtime: the Acer's connection to the Mac (plan, section 5.1).

The Acer sends user_message and client_status events. Each user_message is answered with turn_start, sentence
events and turn_end (or error). Mika answers one message at a time; a few more can wait in a bounded queue,
and any beyond that are refused with an error event.

Each connection runs in an asyncio.TaskGroup: the handler reads events while a worker task runs the turns.
When the Acer disconnects, or the server shuts down (uvicorn closes the connection), the reader returns and
the worker is cancelled, even in the middle of a turn. CancelledError is never swallowed: a swallowed one is
what kept the old server from shutting down (known issues, docs/top_secret.md).

Browsers always send an Origin header, and CORS doesn't cover WebSockets, so the endpoint checks it: a web
page can only connect if its origin is in ServerSettings.allowed_origins. The Acer's Python client sends none.
"""

import asyncio
import logging
from collections.abc import Collection

from fastapi import APIRouter, WebSocket, status
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from mika_shared.events import ClientStatus, RuntimeServerEvent, TurnError, UserMessage, parse_runtime_client_event

from ..config import ServerSettings
from ..state.manager import StateManager
from ..turn.pipeline import FAILED_MESSAGE, ClientGone, TurnRunner

log = logging.getLogger(__name__)

router = APIRouter()

REPLACED = 4001  # close code: a newer connection from the Acer took over
BUSY_MESSAGE = "Mika is busy: too many messages are waiting. Try again in a moment."


@router.websocket("/ws/runtime")
async def runtime(websocket: WebSocket) -> None:
    hub: RuntimeHub = websocket.app.state.services.hub
    origin = websocket.headers.get("origin")
    if not origin_allowed(origin, hub.settings.allowed_origins):
        log.warning("Refused a /ws/runtime connection from origin %r", origin)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)  # before accept, so the browser gets a 403
        return
    await websocket.accept()
    await hub.serve(websocket)


def origin_allowed(origin: str | None, allowed: Collection[str]) -> bool:
    """Browsers always send Origin; the Acer's Python client sends none."""
    return origin is None or origin in allowed


class RuntimeHub:
    """Serves the Acer's connections: the newest one wins, and turns run one at a time across all of them."""

    def __init__(self, runner: TurnRunner, state: StateManager, settings: ServerSettings) -> None:
        self.runner = runner
        self.state = state
        self.settings = settings
        self.turn_lock = asyncio.Lock()
        self._current: RuntimeConnection | None = None

    async def serve(self, websocket: WebSocket) -> None:
        connection = RuntimeConnection(websocket, self)
        previous, self._current = self._current, connection
        if previous is not None:
            # The Acer reconnected while its old connection still looked open: drop the old one and its turn.
            log.warning("A new connection from the Acer replaces the open one")
            await previous.close(REPLACED, "replaced by a new connection")
        log.info("The Acer connected from %s", _address(websocket))
        try:
            await connection.serve()
        finally:
            if self._current is connection:
                self._current = None
            log.info("The Acer's connection from %s closed", _address(websocket))


class RuntimeConnection:
    def __init__(self, websocket: WebSocket, hub: RuntimeHub) -> None:
        self._websocket = websocket
        self._hub = hub
        self._queue: asyncio.Queue[UserMessage] = asyncio.Queue(maxsize=hub.settings.max_pending_messages)
        self._send_lock = asyncio.Lock()

    async def serve(self) -> None:
        """Read events until the Acer disconnects, running its turns meanwhile. Returns when both have stopped."""
        try:
            async with asyncio.TaskGroup() as tasks:
                worker = tasks.create_task(self._run_turns())
                await self._read_events()
                worker.cancel()  # the Acer is gone: stop the turn in progress
        except* ClientGone as group:
            log.warning("The Acer stopped receiving (%s); closing its connection", group.exceptions[0])
            await self.close(status.WS_1011_INTERNAL_ERROR, "sending failed")

    async def send(self, event: RuntimeServerEvent) -> None:
        """Send one event. Raises ClientGone if the Acer can't be reached or doesn't receive in time."""
        try:
            async with asyncio.timeout(self._hub.settings.send_timeout):
                async with self._send_lock:
                    await self._websocket.send_text(event.model_dump_json())
        except (WebSocketDisconnect, OSError, RuntimeError, TimeoutError) as e:
            raise ClientGone(f"sending {event.type} failed: {e!r}") from e

    async def close(self, code: int, reason: str) -> None:
        """Close the connection. Does nothing if it is already closed."""
        try:
            async with asyncio.timeout(self._hub.settings.send_timeout):
                async with self._send_lock:
                    await self._websocket.close(code=code, reason=reason)
        except Exception:  # already closed, or the Acer is gone (CancelledError still propagates)
            pass

    async def _read_events(self) -> None:
        while True:
            message = await self._websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("text")
            if data is None:
                data = message.get("bytes") or b""
            try:
                event = parse_runtime_client_event(data)
            except ValidationError as e:
                log.warning("Invalid event from the Acer: %s", _describe(e))
                await self.send(TurnError(message=f"Invalid event: {_describe(e)}"))
                continue
            if isinstance(event, ClientStatus):
                self._hub.state.on_client_status(event)
                detail = f" ({event.detail})" if event.detail else ""
                log.info("Acer %s: %s%s", event.component.value, event.status.value, detail)
            elif self._hub.state.state.shutting_down:
                await self.send(TurnError(message="The server is shutting down."))
            else:
                try:
                    self._queue.put_nowait(event)
                except asyncio.QueueFull:
                    log.warning("Refused a message from %s: %d already waiting", event.user_id, self._queue.qsize())
                    await self.send(TurnError(message=BUSY_MESSAGE))

    async def _run_turns(self) -> None:
        while True:
            request = await self._queue.get()
            async with self._hub.turn_lock:
                try:
                    await self._hub.runner.run(request, self.send)
                except ClientGone:
                    raise
                except Exception:  # a bug: report it, and keep serving
                    log.exception("A turn failed unexpectedly")
                    await self.send(TurnError(message=FAILED_MESSAGE))


def _describe(error: ValidationError) -> str:
    first = error.errors(include_url=False)[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}" if where else first["msg"]


def _address(websocket: WebSocket) -> str:
    client = websocket.client
    return f"{client.host}:{client.port}" if client else "an unknown address"
