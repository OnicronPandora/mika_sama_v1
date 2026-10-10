"""Try the output filter on sentences (from mika/server, with Ollama running):

    python -m app.filter.check "You look cute today, Pandora~"
    python -m app.filter.check --message "Where do you live?" "My address is 12 Example Street."
    python -m app.filter.check --mode shared "You look cute today, Pandora~"

Uses the files in data/ (personality, filter_policy.yaml, prohibited_words.txt, block_fallbacks.txt).
--mode picks how the classifier and replacer see the turn (FilterSettings.context_mode).
"""

import argparse
import asyncio
import sys
import time

from ..config import FilterSettings, LLMSettings
from ..llm.engine import LLMEngine
from ..memory.prompt import build_turn_messages
from ..personality.engine import build_system_prompt, load_personality
from .ai_classifier import load_filter_policy
from .context import TurnContext
from .policy import build_output_filter


async def run(args: argparse.Namespace) -> None:
    overrides = {key: value for key, value in (("model", args.model), ("ollama_host", args.host)) if value}
    engine = LLMEngine(LLMSettings(**overrides))
    personality, policy = load_personality(), load_filter_policy()
    settings = FilterSettings(context_mode=args.mode)
    output_filter = build_output_filter(engine, personality, settings, policy=policy)
    print(f"{output_filter.words.size} prohibited word(s), {len(output_filter.fallbacks)} fallback line(s)")
    # The turn's prompt, as the server builds it without history or memories ("shared" mode continues it).
    system_prompt = build_system_prompt(personality, stream_rules=policy.prompt_section())
    prompt = build_turn_messages(
        system_prompt=system_prompt,
        history=[],
        memories=None,
        user_message=args.message,
        num_predict=engine.settings.num_predict,
    )
    try:
        print(f"Loading and warming up {engine.settings.model} ({args.mode} mode) ...", flush=True)
        await engine.load_model(system_prompt if args.mode == "shared" else "")
        context = TurnContext(user_message=args.message, prompt=tuple(prompt))
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
    parser.add_argument("--mode", choices=["separate", "shared"], default="separate", help="classifier context mode")
    parser.add_argument("--model", help="Ollama model (default: the server's, llama3.1:8b)")
    parser.add_argument("--host", help="Ollama URL (default: http://localhost:11434)")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
