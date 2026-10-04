"""Try the output filter on sentences (from mika/server, with Ollama running):

    python -m app.filter.check "You look cute today, Pandora~"
    python -m app.filter.check --message "Where do you live?" "My address is 12 Example Street."

Uses the files in data/ (personality, filter_policy.yaml, prohibited_words.txt, block_fallbacks.txt).
"""

import argparse
import asyncio
import sys
import time

from ..config import FilterSettings, LLMSettings
from ..llm.engine import LLMEngine
from ..personality.engine import load_personality
from .context import TurnContext
from .policy import build_output_filter


async def run(args: argparse.Namespace) -> None:
    overrides = {key: value for key, value in (("model", args.model), ("ollama_host", args.host)) if value}
    engine = LLMEngine(LLMSettings(**overrides))
    output_filter = build_output_filter(engine, load_personality(), FilterSettings())
    print(f"{output_filter.words.size} prohibited word(s), {len(output_filter.fallbacks)} fallback line(s)")
    try:
        print(f"Loading and warming up {engine.settings.model} ...", flush=True)
        await engine.load_model()
        context = TurnContext(user_message=args.message)
        for sentence in args.sentences:
            start = time.perf_counter()
            result = await output_filter.check(sentence, context)
            elapsed = time.perf_counter() - start
            print(f"\n{sentence!r}\n  {result.action.value} in {elapsed:.2f} s", flush=True)
            if result.filter_response:
                print(f"  Mika says instead: {result.filter_response}")
            if result.reason:
                print(f"  reason: {result.reason}")
    finally:
        await engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sentences", nargs="+", help="sentences Mika might say")
    parser.add_argument("--message", default="Hi Mika!", help="the viewer message they reply to")
    parser.add_argument("--model", help="Ollama model (default: the server's, llama3.1:8b)")
    parser.add_argument("--host", help="Ollama URL (default: http://localhost:11434)")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
