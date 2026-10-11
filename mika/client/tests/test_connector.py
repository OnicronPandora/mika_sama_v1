import asyncio

from fakes import FakeMac

from app.ws import connector as connector_module
from app.ws.connector import REPLACED, RuntimeConnector
from mika_shared.enums import Emotion, MessageSource
from mika_shared.events import TurnStart, UserMessage

HELLO = UserMessage(user_id="admin", message="Hi Mika!", source=MessageSource.CHAT)


class Recorder:
    def __init__(self) -> None:
        self.events: list = []
        self.log: list[str] = []

    async def on_event(self, event) -> None:
        self.events.append(event)

    async def on_connected(self) -> None:
        self.log.append("connected")

    async def on_disconnected(self) -> None:
        self.log.append("disconnected")


def connector_for(url: str, recorder: Recorder) -> RuntimeConnector:
    return RuntimeConnector(
        url,
        on_event=recorder.on_event,
        on_connected=recorder.on_connected,
        on_disconnected=recorder.on_disconnected,
        max_delay=0.1,
    )


async def until(condition, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


async def test_events_flow_both_ways():
    recorder = Recorder()
    async with FakeMac().running() as mac:
        connector = connector_for(mac.url, recorder)
        task = asyncio.create_task(connector.run())
        await until(lambda: connector.connected)
        assert await connector.send(HELLO)
        assert await mac.next() == HELLO
        await mac.connection.send("not an event")  # ignored
        await mac.send(TurnStart(turn_id="t1", emotion=Emotion.HAPPY))
        await until(lambda: recorder.events)
        assert recorder.events == [TurnStart(turn_id="t1", emotion=Emotion.HAPPY)]
        task.cancel()
    assert recorder.log[0] == "connected"


async def test_reconnects_when_the_mac_drops_the_connection():
    recorder = Recorder()
    async with FakeMac().running() as mac:
        connector = connector_for(mac.url, recorder)
        task = asyncio.create_task(connector.run())
        await until(lambda: connector.connected)
        await mac.connection.close()
        await until(lambda: recorder.log == ["connected", "disconnected", "connected"])
        assert await connector.send(HELLO)
        task.cancel()


async def test_nothing_is_sent_without_the_mac():
    recorder = Recorder()
    connector = connector_for("ws://127.0.0.1:9/ws/runtime", recorder)  # nothing listens there
    task = asyncio.create_task(connector.run())
    await asyncio.sleep(0.2)
    assert not connector.connected
    assert not await connector.send(HELLO)
    task.cancel()
    assert recorder.log == []


async def test_when_replaced_by_another_client_it_waits_longer(monkeypatch):
    monkeypatch.setattr(connector_module, "REPLACED_DELAY", 0.3)
    recorder = Recorder()
    async with FakeMac().running() as mac:
        connector = connector_for(mac.url, recorder)
        task = asyncio.create_task(connector.run())
        await until(lambda: connector.connected)
        await mac.connection.close(REPLACED, "replaced by a new connection")
        await until(lambda: recorder.log == ["connected", "disconnected"])
        await asyncio.sleep(0.15)
        assert not connector.connected  # still waiting
        await until(lambda: connector.connected)
        task.cancel()
