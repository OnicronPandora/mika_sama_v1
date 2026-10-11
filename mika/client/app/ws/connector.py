"""The Acer's connection to the Mac's /ws/runtime (plan, section 5.1). It reconnects until the client stops.

One connection at a time: the Mac lets a new connection from the Acer replace an open one (close code 4001),
so a second client would keep knocking this one off; after that close it waits longer before reconnecting.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from mika_shared.events import RuntimeClientEvent, RuntimeServerEvent, parse_runtime_server_event

log = logging.getLogger(__name__)

REPLACED = 4001  # the Mac's close code when a newer connection from the Acer took over
REPLACED_DELAY = 30.0


class RuntimeConnector:
    def __init__(
        self,
        url: str,
        *,
        on_event: Callable[[RuntimeServerEvent], Awaitable[None]],
        on_connected: Callable[[], Awaitable[None]],
        on_disconnected: Callable[[], Awaitable[None]],
        send_timeout: float = 10.0,
        max_delay: float = 10.0,
    ) -> None:
        self.url = url
        self._on_event = on_event
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._send_timeout = send_timeout
        self._max_delay = max_delay
        self._connection: ClientConnection | None = None

    @property
    def connected(self) -> bool:
        return self._connection is not None

    async def send(self, event: RuntimeClientEvent) -> bool:
        """Send one event. False if the Mac isn't connected or doesn't take it in time."""
        connection = self._connection
        if connection is None:
            return False
        try:
            async with asyncio.timeout(self._send_timeout):
                await connection.send(event.model_dump_json())
            return True
        except (ConnectionClosed, OSError, TimeoutError):
            return False

    async def run(self) -> None:
        first_delay = min(1.0, self._max_delay)
        delay, failures = first_delay, 0
        while True:
            try:
                async with connect(self.url, open_timeout=10) as connection:
                    log.info("Connected to the Mac at %s", self.url)
                    delay, failures = first_delay, 0
                    self._connection = connection
                    try:
                        await self._on_connected()
                        await self._read(connection)
                    finally:
                        self._connection = None
                        await self._on_disconnected()
                code = connection.close_code
                log.warning("The Mac closed the connection (code %s)", code)
                if code == REPLACED:
                    log.warning("Another client connected to the Mac in this one's place; retrying in %.0f s", REPLACED_DELAY)
                    await asyncio.sleep(REPLACED_DELAY)
                    continue
            except (OSError, TimeoutError, WebSocketException) as e:
                failures += 1
                if failures == 1 or failures % 10 == 0:  # don't flood the log while the Mac is off
                    log.warning("Can't reach the Mac at %s (%s); retrying", self.url, e)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._max_delay)

    async def _read(self, connection: ClientConnection) -> None:
        try:
            async for data in connection:
                try:
                    event = parse_runtime_server_event(data)
                except ValidationError as e:
                    log.warning("Invalid event from the Mac: %s", e.errors(include_url=False)[0]["msg"])
                    continue
                await self._on_event(event)
        except ConnectionClosed:
            pass
