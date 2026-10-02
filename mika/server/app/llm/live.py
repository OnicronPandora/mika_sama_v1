"""Print a live reply as tagged sentences (Phase 3 check). Run from mika/server:

    python -m app.llm.live "Hi Mika! How was your day?"
    python -m app.llm.live --model llama3:latest --show-prompt "Hello!"

Uses data/personality.yaml without learned traits. Times are measured after the model is loaded.
"""

import argparse
import asyncio
import sys
import time

from ..config import LLMSettings
from ..personality.engine import build_system_prompt, load_personality
from .engine import LLMEngine
from .streaming import EmotionDecided, SentenceReady, reply_events


async def run(args: argparse.Namespace) -> None:
    overrides = {key: value for key, value in (("model", args.model), ("ollama_host", args.host)) if value}
    engine = LLMEngine(LLMSettings(**overrides))
    prompt = build_system_prompt(load_personality())
    if args.show_prompt:
        print(f"--- system prompt ---\n{prompt}\n---------------------")
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": args.message}]
    raw: list[str] = []

    async def tokens():
        async for token in engine.stream_chat(messages):
            raw.append(token)
            yield token

    try:
        print(f"Loading {engine.settings.model} ...", flush=True)
        await engine.load_model()
        print(f"Pandora: {args.message}", flush=True)
        start = time.perf_counter()
        count = 0
        async for event in reply_events(tokens()):
            elapsed = time.perf_counter() - start
            match event:
                case EmotionDecided(emotion, tag_found):
                    note = "" if tag_found else "  (no valid tag: fallback)"
                    print(f"[{elapsed:5.2f}s] emotion: {emotion.value}{note}", flush=True)
                case SentenceReady(text):
                    print(f"[{elapsed:5.2f}s] sentence {count}: {text}", flush=True)
                    count += 1
        print(f"[{time.perf_counter() - start:5.2f}s] done: {count} sentence(s)")
        print(f"raw LLM output: {''.join(raw)!r}")
    finally:
        await engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("message", help="what Pandora says to Mika")
    parser.add_argument("--model", help="Ollama model (default: the server's, llama3.1:8b)")
    parser.add_argument("--host", help="Ollama URL (default: http://localhost:11434)")
    parser.add_argument("--show-prompt", action="store_true", help="print the system prompt first")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the raw reply may contain emoji
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
