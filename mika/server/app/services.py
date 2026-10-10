"""Everything the server runs on, started by the FastAPI lifespan and closed in reverse order at shutdown.

Startup reads the files in data/ and the learned traits, loads the embedding model, and warms Ollama up with
the admin's prompt (the model loads, and Pandora's first message only needs its own part read). It fails
loudly when the database or Ollama can't be reached: start them first.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool

from mika_shared.payloads import ADMIN_USER_ID

from .api.ws_runtime import RuntimeHub
from .config import Settings
from .db import queries
from .db.pool import open_pool
from .filter.ai_classifier import FilterPolicy, load_filter_policy
from .filter.policy import build_output_filter
from .llm.engine import LLMEngine, ReplyStats
from .memory.archive import Archive, PgArchive
from .memory.conversation import Conversation
from .memory.rag import Embedder, LocalEmbedder, MemoryStore
from .personality.engine import Personality, build_system_prompt, load_personality
from .state.manager import StateManager
from .turn.pipeline import TurnRunner

log = logging.getLogger(__name__)
llm_log = logging.getLogger("app.llm")


@dataclass
class Services:
    settings: Settings
    state: StateManager
    engine: LLMEngine
    conversation: Conversation
    runner: TurnRunner
    hub: RuntimeHub
    pool: AsyncConnectionPool | None = None  # None when turns aren't kept in PostgreSQL (tests, bench)


def build_services(
    settings: Settings,
    *,
    engine: LLMEngine,
    archive: Archive,
    personality: Personality,
    policy: FilterPolicy,
    traits: Sequence[str] = (),
    pool: AsyncConnectionPool | None = None,
) -> Services:
    """Wire the parts together (no I/O beyond reading the filter's files in data/)."""
    system_prompt = build_system_prompt(personality, traits)
    state = StateManager(personality)
    conversation = Conversation(archive, settings.memory)
    runner = TurnRunner(
        engine=engine,
        output_filter=build_output_filter(engine, personality, settings.filter, policy=policy),
        conversation=conversation,
        state=state,
        system_prompt=system_prompt,
        assistant=personality.name,
        settings=settings,
    )
    hub = RuntimeHub(runner, state, settings.server)
    return Services(settings, state, engine, conversation, runner, hub, pool)


def log_llm_call(label: str, stats: ReplyStats, seconds: float) -> None:
    """Every LLM call's timings go to server.log: they show how much of each prompt Ollama had to read."""
    llm_log.info("%s in %.2f s: %s", label, seconds, stats)


@asynccontextmanager
async def open_services(
    settings: Settings, *, engine: LLMEngine | None = None, embedder: Embedder | None = None
) -> AsyncIterator[Services]:
    """The server's services. The tests pass a fake engine and embedder."""
    async with AsyncExitStack() as stack:
        started = time.perf_counter()
        personality, policy = load_personality(), load_filter_policy()

        pool = await open_pool(settings.db)
        stack.push_async_callback(pool.close)
        async with pool.connection() as conn:
            traits = await queries.active_traits(conn)
        log.info("Database ready (%s:%s/%s), %d learned trait(s)", settings.db.host, settings.db.port, settings.db.name, len(traits))

        if embedder is None:
            embedder = LocalEmbedder(settings.memory)
            await asyncio.to_thread(embedder.load)  # the first start downloads the model (0.13 GB)
            log.info("Embedding model ready: %s", settings.memory.embedding_model)
        if engine is None:
            engine = LLMEngine(settings.llm, on_call=log_llm_call)
            stack.push_async_callback(engine.close)

        archive = PgArchive(pool, MemoryStore(embedder, settings.memory, assistant=personality.name))
        services = build_services(
            settings, engine=engine, archive=archive, personality=personality, policy=policy, traits=traits, pool=pool
        )
        services.state.set_service("database", "ok")
        services.state.set_service("embeddings", "ok")

        log.info("Loading %s and reading %s's prompt ...", settings.llm.model, settings.memory.admin_name)
        try:
            async with asyncio.timeout(settings.llm.warm_up_timeout):
                await engine.warm_up(await services.runner.prefix(ADMIN_USER_ID), label="startup")
        except ConnectionError:
            log.error("Ollama isn't reachable at %s: start it, then start the server again", settings.llm.ollama_host)
            raise
        services.state.set_service("ollama", "ok")
        log.info("Services ready in %.1f s", time.perf_counter() - started)
        yield services
