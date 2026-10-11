"""The client end to end: a fake Mac, the client app on localhost, fake browser pages, fake voice and ears."""

import asyncio
import base64
import io
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import numpy as np
import pytest
import uvicorn
from fakes import FakeMac, FakeTranscriber, FakeVoice, fast_settings, open_fake_client, quiet, speech
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidStatus

from app.api.ws_chat import Page
from app.main import create_app
from app.relay import UNREACHABLE
from mika_shared.enums import ClientComponent, ComponentState, Emotion, FilterAction, Intent, MessageSource, TranscriptRole
from mika_shared.events import (
    AdminMessage,
    AudioChunk,
    ChatTurnEnd,
    ClientStatus,
    EmotionUpdate,
    Notice,
    PlaybackFinished,
    Sentence,
    Transcript,
    TurnEnd,
    TurnError,
    TurnStart,
    UserMessage,
    parse_chat_server_event,
)


@asynccontextmanager
async def running(app) -> AsyncIterator[str]:
    """Serve the client app on a free localhost port. Yields the /ws/chat URL."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, lifespan="on"))
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            if task.done():
                task.result()
            await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}/ws/chat"
    finally:
        server.should_exit = True
        await task


async def receive(page: ClientConnection, count: int = 1) -> list:
    async with asyncio.timeout(5):
        return [parse_chat_server_event(await page.recv()) for _ in range(count)]


async def until(condition, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


def turn(*sentences: str, turn_id: str = "t1") -> list:
    """What the Mac sends for one reply."""
    events = [TurnStart(turn_id=turn_id, emotion=Emotion.HAPPY)]
    events += [Sentence(turn_id=turn_id, seq=i, text=text, action=FilterAction.ALLOW) for i, text in enumerate(sentences)]
    return [*events, TurnEnd(turn_id=turn_id, last_seq=len(sentences) - 1, intent=Intent.CASUAL_CONVERSATION)]


async def test_a_typed_message_is_spoken_in_order_and_the_mic_waits_for_the_last_sentence():
    """Plan, Phase 7 "done when", with a fake Mac, voice and pages."""
    async with FakeMac().running() as mac:
        app = create_app(fast_settings(mac.url), services=open_fake_client(FakeVoice(), FakeTranscriber()))
        async with running(app) as url, connect(url + "?page=avatar") as avatar, connect(url + "?page=admin") as admin:
            gate = app.state.services.gate
            await admin.send(AdminMessage(message="Hi Mika!").model_dump_json())
            assert await mac.next(UserMessage) == UserMessage(user_id="admin", message="Hi Mika!", source=MessageSource.CHAT)
            assert await receive(admin) == [Transcript(role=TranscriptRole.ADMIN, text="Hi Mika!")]
            assert gate.muted  # from the message on: Mika is about to answer

            await mac.send(*turn("Hi Pandora!", "How was your day?"))
            emotion, first, second, end = await receive(avatar, 4)
            assert emotion == EmotionUpdate(turn_id="t1", emotion=Emotion.HAPPY)
            assert [(chunk.seq, chunk.text) for chunk in (first, second)] == [(0, "Hi Pandora!"), (1, "How was your day?")]
            with wave.open(io.BytesIO(base64.b64decode(second.audio_b64))) as audio:
                assert audio.getframerate() == second.sample_rate == 32000
            assert end == ChatTurnEnd(turn_id="t1", last_seq=1)
            assert await receive(admin, 2) == [
                Transcript(role=TranscriptRole.MIKA, text="Hi Pandora!"),
                Transcript(role=TranscriptRole.MIKA, text="How was your day?"),
            ]

            await avatar.send(PlaybackFinished(turn_id="t1", seq=0).model_dump_json())
            await asyncio.sleep(0.1)
            assert gate.muted  # the last sentence is still playing
            await avatar.send(PlaybackFinished(turn_id="t1", seq=1).model_dump_json())
            await until(lambda: not gate.muted)


async def test_the_mac_hears_how_the_acers_parts_are_doing():
    async with FakeMac().running() as mac:
        app = create_app(fast_settings(mac.url), services=open_fake_client(FakeVoice(), FakeTranscriber()))
        async with running(app) as url:
            async with connect(url + "?page=avatar"):
                ready: set[ClientComponent] = set()
                expected = {ClientComponent.TTS, ClientComponent.STT, ClientComponent.AVATAR_PAGE}
                while ready != expected:
                    status = await mac.next(ClientStatus)
                    if status.status is ComponentState.READY:
                        ready.add(status.component)
            assert await mac.next(ClientStatus) == ClientStatus(component=ClientComponent.AVATAR_PAGE, status=ComponentState.STOPPED)


async def test_speaking_sends_a_voice_message_and_mutes_the_mic():
    transcriber = FakeTranscriber("Hello Mika, are you there?")
    audio = np.concatenate([quiet(0.3), speech(0.8), quiet(1.0)])
    async with FakeMac().running() as mac:
        app = create_app(fast_settings(mac.url), services=open_fake_client(FakeVoice(), transcriber, audio))
        async with running(app) as url, connect(url + "?page=admin") as admin:
            message = await mac.next(UserMessage, timeout=10)
            assert message == UserMessage(user_id="admin", message="Hello Mika, are you there?", source=MessageSource.VOICE)
            assert await receive(admin) == [Transcript(role=TranscriptRole.ADMIN, text="Hello Mika, are you there?")]
            assert app.state.services.gate.muted


async def test_a_message_the_mac_cant_get_is_reported_on_the_admin_page():
    app = create_app(fast_settings(), services=open_fake_client(FakeVoice(), FakeTranscriber()))  # no Mac
    async with running(app) as url, connect(url + "?page=admin") as admin:
        await admin.send(AdminMessage(message="Hi?").model_dump_json())
        assert await receive(admin) == [Notice(text=UNREACHABLE)]
        assert not app.state.services.gate.muted


async def test_an_error_from_the_mac_is_shown_and_unmutes():
    async with FakeMac().running() as mac:
        app = create_app(fast_settings(mac.url), services=open_fake_client(FakeVoice(), FakeTranscriber()))
        async with running(app) as url, connect(url + "?page=admin") as admin:
            await admin.send(AdminMessage(message="Hi!").model_dump_json())
            await mac.next(UserMessage)
            await receive(admin)  # the transcript
            await mac.send(TurnError(turn_id="t1", message="Mika couldn't answer this time."))
            assert await receive(admin) == [Notice(text="Mika couldn't answer this time.")]
            await until(lambda: not app.state.services.gate.muted)


async def test_losing_the_mac_mid_reply_ends_the_turn_on_the_page():
    async with FakeMac().running() as mac:
        app = create_app(fast_settings(mac.url), services=open_fake_client(FakeVoice(), FakeTranscriber()))
        async with running(app) as url, connect(url + "?page=avatar") as avatar, connect(url + "?page=admin") as admin:
            await admin.send(AdminMessage(message="Tell me a story.").model_dump_json())
            await mac.next(UserMessage)
            await mac.send(*turn("Once upon a time.", "There was a cat.")[:2])  # turn_start and the first sentence
            emotion, chunk = await receive(avatar, 2)
            await mac.connection.close()
            assert await receive(avatar) == [ChatTurnEnd(turn_id="t1", last_seq=0)]  # play what came
            await until(lambda: not app.state.services.gate.muted)


async def test_pages_must_say_which_they_are_and_come_from_the_dev_server():
    app = create_app(fast_settings(), services=open_fake_client(FakeVoice(), FakeTranscriber()))
    async with running(app) as url:
        for page_url, origin in ((url, None), (url + "?page=avatar", "http://evil.example")):
            with pytest.raises(InvalidStatus) as refused:
                async with connect(page_url, origin=origin):
                    pass
            assert refused.value.response.status_code == 403
        async with connect(url + "?page=avatar", origin="http://localhost:5173"):
            pass


async def test_health():
    app = create_app(fast_settings(), services=open_fake_client(FakeVoice(), FakeTranscriber()))
    async with running(app) as url:
        base = url.replace("ws://", "http://").removesuffix("/ws/chat")
        async with connect(url + "?page=avatar"), httpx.AsyncClient() as client:
            services = app.state.services
            await until(lambda: services.pages.count(Page.AVATAR) == 1 and len(services.relay.statuses) == 3)
            health = (await client.get(base + "/health")).json()
    assert health == {
        "status": "ok",
        "mac": "not connected",
        "parts": {"avatar_page": "ready", "tts": "ready", "stt": "ready"},
        "pages": {"avatar": 1, "admin": 0},
        "microphone": "open",
    }
