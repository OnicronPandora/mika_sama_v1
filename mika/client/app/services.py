"""Everything the client runs, started by the FastAPI lifespan and stopped at shutdown.

The background tasks share one asyncio.TaskGroup: the connection to the Mac, the speaker, loading the voice,
and the listener. The models load in the background (GenieTTS about 15 s with its warm-up, Whisper about 2 s),
so the pages and the Mac can connect at once; the Mac hears about each part through client_status.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mika_shared.enums import ClientComponent, ComponentState, MessageSource

from .api.ws_chat import PageHub
from .config import ClientSettings
from .relay import Relay
from .stt.engine import Transcriber, WhisperTranscriber
from .stt.gate import HalfDuplexGate
from .stt.listener import AudioSource, Listener, Microphone
from .tts.engine import GenieVoice
from .tts.speaker import Speaker
from .ws.connector import RuntimeConnector

log = logging.getLogger(__name__)


@dataclass
class ClientServices:
    settings: ClientSettings
    pages: PageHub
    gate: HalfDuplexGate
    relay: Relay
    connector: RuntimeConnector


@asynccontextmanager
async def open_client(
    settings: ClientSettings,
    *,
    voice=None,
    transcriber: Transcriber | None = None,
    source: AudioSource | None = None,
    vad=None,
) -> AsyncIterator[ClientServices]:
    """The client's parts. The tests pass a fake voice, transcriber, audio source and voice activity detector."""
    voice = voice or GenieVoice(settings.voice)
    transcriber = transcriber or WhisperTranscriber(settings.listen)
    source = source or Microphone(settings.listen.input_device)

    pages = PageHub(send_timeout=settings.send_timeout)
    gate = HalfDuplexGate(echo_guard=settings.listen.echo_guard)
    voice_ready = asyncio.Event()
    speaker = Speaker(voice, pages.to_avatar, lambda *spoken: relay.on_spoken(*spoken), ready=voice_ready)
    connector = RuntimeConnector(
        settings.server_ws_url,
        on_event=lambda event: relay.on_mac_event(event),
        on_connected=lambda: relay.on_mac_connected(),
        on_disconnected=lambda: relay.on_mac_disconnected(),
        send_timeout=settings.send_timeout,
        max_delay=settings.reconnect_max_delay,
    )
    relay = Relay(
        send_to_mac=connector.send,
        pages=pages,
        speaker=speaker,
        gate=gate,
        playback_margin=settings.listen.playback_margin,
    )
    listener = Listener(
        source,
        transcriber,
        gate,
        settings.listen,
        on_utterance=lambda text: relay.user_said(text, MessageSource.VOICE),
        vad=vad,
    )
    services = ClientServices(settings, pages, gate, relay, connector)
    try:
        async with asyncio.TaskGroup() as tasks:
            background = [
                tasks.create_task(connector.run(), name="connector"),
                tasks.create_task(speaker.run(), name="speaker"),
                tasks.create_task(_start_voice(voice, voice_ready, relay), name="voice"),
                tasks.create_task(_listen(listener, transcriber, relay), name="listener"),
            ]
            try:
                yield services
            finally:
                for task in background:
                    task.cancel()
    finally:
        if isinstance(voice, GenieVoice):
            voice.close()


async def _start_voice(voice, ready: asyncio.Event, relay: Relay) -> None:
    await relay.set_status(ClientComponent.TTS, ComponentState.STARTING)
    try:
        started = time.perf_counter()
        await asyncio.to_thread(voice.load)
        await voice.synthesize("Warming up.")  # the first sentence also prepares the reference audio
        log.info("Mika's voice is ready (%.1f s)", time.perf_counter() - started)
        await relay.set_status(ClientComponent.TTS, ComponentState.READY)
    except Exception as e:  # (CancelledError still propagates)
        log.exception("Mika's voice failed to load; sentences will be silent")
        await relay.set_status(ClientComponent.TTS, ComponentState.ERROR, detail=_detail(e))
    finally:
        ready.set()  # the speaker stops waiting either way


async def _listen(listener: Listener, transcriber: Transcriber, relay: Relay) -> None:
    await relay.set_status(ClientComponent.STT, ComponentState.STARTING)
    try:
        started = time.perf_counter()
        await asyncio.to_thread(transcriber.load)
        log.info("Speech to text is ready (%.1f s)", time.perf_counter() - started)
        await relay.set_status(ClientComponent.STT, ComponentState.READY)
        await listener.run()
    except Exception as e:  # no model, no microphone (CancelledError still propagates)
        log.exception("Listening stopped; Pandora can still type")
        await relay.set_status(ClientComponent.STT, ComponentState.ERROR, detail=_detail(e))


def _detail(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:200]
