"""/ws/runtime over real WebSockets: uvicorn on localhost, a fake Acer, a scripted LLM (plan, section 8)."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import pytest
import uvicorn
from fakes import HANG, FakeEngine, fake_settings, open_fake_services, verdict
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.api.ws_runtime import BUSY_MESSAGE, REPLACED
from app.main import create_app
from app.memory.archive import MemoryArchive
from mika_shared.enums import ClientComponent, ComponentState, Emotion, FilterAction, Intent, MessageSource
from mika_shared.events import (
    ClientStatus,
    Sentence,
    TurnEnd,
    TurnError,
    TurnStart,
    UserMessage,
    parse_runtime_server_event,
)


def make_app(engine: FakeEngine, archive: MemoryArchive | None = None, **server):
    return create_app(fake_settings(**server), services=lambda settings: open_fake_services(settings, engine, archive))


@asynccontextmanager
async def running(app) -> AsyncIterator[str]:
    """Serve the app with uvicorn on a free localhost port. Yields the /ws/runtime URL."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, lifespan="on"))
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            if task.done():
                task.result()  # startup failed: raise its error
            await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}/ws/runtime"
    finally:
        server.should_exit = True
        await task


def user_message(text: str = "Hi Mika!") -> str:
    return UserMessage(user_id="admin", message=text, source=MessageSource.CHAT).model_dump_json()


async def receive(acer: ClientConnection, count: int = 1) -> list:
    async with asyncio.timeout(5):
        return [parse_runtime_server_event(await acer.recv()) for _ in range(count)]


async def until(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not condition():
            await asyncio.sleep(0.01)


async def test_a_full_turn_over_the_websocket():
    """Plan, Phase 6 "done when": a fake Acer and a fake LLM through a whole turn."""
    engine = FakeEngine(verdict(True), verdict(True), replies=[["[happy] Hi Pandora! How was your day?"]])
    archive = MemoryArchive()
    app = make_app(engine, archive)
    async with running(app) as url, connect(url) as acer:
        await acer.send(ClientStatus(component=ClientComponent.TTS, status=ComponentState.READY).model_dump_json())
        await acer.send(user_message())
        start, first, second, end = await receive(acer, 4)
        await until(lambda: archive.records)
    turn_id = start.turn_id
    assert [start, first, second, end] == [
        TurnStart(turn_id=turn_id, emotion=Emotion.HAPPY),
        Sentence(turn_id=turn_id, seq=0, text="Hi Pandora!", action=FilterAction.ALLOW),
        Sentence(turn_id=turn_id, seq=1, text="How was your day?", action=FilterAction.ALLOW),
        TurnEnd(turn_id=turn_id, last_seq=1, intent=Intent.CASUAL_CONVERSATION),
    ]
    assert archive.records[0].result.reply == "Hi Pandora! How was your day?"
    assert app.state.services.state.client_ready(ClientComponent.TTS)


async def test_browser_pages_from_other_origins_are_refused():
    async with running(make_app(FakeEngine(), allowed_origins=("http://localhost:5173",))) as url:
        with pytest.raises(InvalidStatus) as refused:
            async with connect(url, origin="http://evil.example"):
                pass
        assert refused.value.response.status_code == 403
        async with connect(url, origin="http://localhost:5173"):  # an allowed page
            pass
        async with connect(url):  # the Acer's client sends no Origin
            pass


async def test_invalid_events_get_an_error_and_the_connection_stays_open():
    engine = FakeEngine(verdict(True), replies=[["[happy] Hi!"]])
    async with running(make_app(engine)) as url, connect(url) as acer:
        await acer.send("not json")
        await acer.send('{"type": "user_message", "user_id": "admin", "message": "   ", "source": "chat"}')
        not_json, blank = await receive(acer, 2)
        assert not_json.turn_id is None and not_json.message.startswith("Invalid event: Invalid JSON")
        assert blank.message.startswith("Invalid event: user_message.message")
        await acer.send(user_message())
        assert [type(event) for event in await receive(acer, 3)] == [TurnStart, Sentence, TurnEnd]


async def test_messages_beyond_the_queue_are_refused():
    engine = FakeEngine(replies=[["[happy] Hi", HANG]])
    async with running(make_app(engine, max_pending_messages=1)) as url, connect(url) as acer:
        await acer.send(user_message("first"))  # its reply never ends
        await receive(acer)  # turn_start
        await acer.send(user_message("second"))  # waits in the queue
        await acer.send(user_message("third"))  # no room left
        assert await receive(acer) == [TurnError(turn_id=None, message=BUSY_MESSAGE)]


async def test_closing_the_connection_cancels_its_turn():
    engine = FakeEngine(verdict(True), replies=[["[happy] Hi", HANG], ["[happy] Back!"]])
    archive = MemoryArchive()
    async with running(make_app(engine, archive)) as url:
        async with connect(url) as acer:
            await acer.send(user_message())
            await receive(acer)  # turn_start: the reply is being generated
        await until(lambda: engine.open_streams == 0)  # the Acer left: the turn was cancelled
        async with connect(url) as acer:
            await acer.send(user_message("Back?"))
            assert [type(event) for event in await receive(acer, 3)] == [TurnStart, Sentence, TurnEnd]
            await until(lambda: archive.records)
    assert [record.user_message for record in archive.records] == ["Back?"]  # the cancelled turn wasn't saved


async def test_a_new_connection_replaces_the_old_one():
    engine = FakeEngine(verdict(True), replies=[["[happy] Hi", HANG], ["[happy] Hi again!"]])
    async with running(make_app(engine)) as url:
        async with connect(url) as old:
            await old.send(user_message())
            await receive(old)  # turn_start
            async with connect(url) as new:
                with pytest.raises(ConnectionClosed) as closed:
                    await receive(old)
                assert closed.value.rcvd.code == REPLACED
                await new.send(user_message("Hi again"))
                assert [type(event) for event in await receive(new, 3)] == [TurnStart, Sentence, TurnEnd]
    assert engine.open_streams == 0  # the old turn was cancelled
