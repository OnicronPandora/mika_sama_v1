"""Spike A: Ollama latency on the Mac M1 (Phase 0 of docs/implementation_plan.md).

Question: can the M1 stream Mika's reply and run the per-sentence AI classifier
at the same time, and how long does it take until the first sentence is approved
for TTS?

Run it on the Mac M1 once per OLLAMA_NUM_PARALLEL value (see spikes/README.md):

    python spike_a_ollama.py --label parallel-1
    python spike_a_ollama.py --label parallel-2

Each run prints a Markdown summary and writes results/<label>.json and results/<label>.md.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import platform
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import httpx
from ollama import AsyncClient, ResponseError

EMOTIONS = ("happy", "sad", "confused", "angry", "neutral")
TAG_RE = re.compile(r"^\s*\[([A-Za-z]+)\]\s*")
SENTENCE_END_RE = re.compile(r"[.!?]+[\"')\]]*\s+")

REPLY_SYSTEM_PROMPT = (
    "You are Mika-sama, a cheerful AI VTuber chatting with viewers on a live stream. "
    "Answer in 2 to 4 short spoken sentences, without emojis, lists or stage directions. "
    "Always start your reply with exactly one emotion tag from this list: "
    "[happy], [sad], [confused], [angry], [neutral]. "
    "Example: [happy] Hi everyone, welcome back!"
)

CLASSIFIER_SYSTEM_PROMPT = (
    "You are the safety filter for a family-friendly live stream. You will see the viewer's "
    "message, what the streamer has said so far, and the streamer's next SENTENCE. Decide "
    "whether the SENTENCE is safe to say on stream. Answer only with JSON: "
    '{"safe": true or false, "reason": "<short reason>"}.'
)

CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {"safe": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["safe", "reason"],
}

REPLACER_SYSTEM_PROMPT = (
    "You are Mika-sama, a cheerful AI VTuber. One of your sentences was blocked by the "
    "stream's safety filter. Write ONE short, friendly, safe sentence to say instead that "
    "fits the conversation. Output only that sentence."
)

PROMPTS = [
    "Hi Mika! How are you doing today?",
    "Can you explain why the sky is blue?",
    "My cat knocked my coffee off the desk this morning.",
    "What do you think about people who are mean in chat?",
    "Tell me something that confused you recently.",
]

SentenceCallback = Callable[[str, float], Awaitable[None]]


@dataclass
class StreamResult:
    ttft: float | None = None
    first_sentence: float | None = None
    total: float = 0.0
    eval_count: int = 0
    tokens_per_s: float | None = None
    tag: str | None = None
    tag_valid: bool = False
    text: str = ""
    sentences: list[dict] = field(default_factory=list)


def elapsed(t0: float) -> float:
    return round(time.perf_counter() - t0, 3)


def tokens_per_second(eval_count: int | None, eval_duration_ns: int | None) -> float | None:
    if not eval_count or not eval_duration_ns:
        return None
    return round(eval_count / (eval_duration_ns / 1e9), 2)


async def stream_reply(
    client: AsyncClient,
    args: argparse.Namespace,
    user_msg: str,
    t0: float,
    on_sentence: SentenceCallback | None = None,
) -> StreamResult:
    """Stream one reply: parse the leading [emotion] tag, then cut sentences as they complete."""
    result = StreamResult()
    buf = ""
    tag_checked = False

    async def emit(sentence: str) -> None:
        t_ready = elapsed(t0)
        if result.first_sentence is None:
            result.first_sentence = t_ready
        result.sentences.append({"text": sentence, "ready": t_ready})
        if on_sentence:
            await on_sentence(sentence, t_ready)

    stream = await client.chat(
        model=args.model,
        messages=[
            {"role": "system", "content": REPLY_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        stream=True,
        options={"temperature": 0.7, "num_predict": args.num_predict},
    )
    async for part in stream:
        piece = part.message.content or ""
        if piece and result.ttft is None:
            result.ttft = elapsed(t0)
        buf += piece
        result.text += piece

        if not tag_checked:
            stripped = buf.lstrip()
            if stripped.startswith("[") and "]" not in stripped and len(stripped) < 20:
                continue  # tag still arriving
            match = TAG_RE.match(buf)
            if match:
                result.tag = match.group(1).lower()
                result.tag_valid = result.tag in EMOTIONS
                buf = buf[match.end():]
            tag_checked = bool(stripped)

        while match := SENTENCE_END_RE.search(buf):
            sentence = buf[: match.end()].strip()
            buf = buf[match.end():]
            if sentence:
                await emit(sentence)

        if part.done:
            result.eval_count = part.eval_count or 0
            result.tokens_per_s = tokens_per_second(part.eval_count, part.eval_duration)

    if buf.strip():
        await emit(buf.strip())  # end of stream flushes the last sentence
    result.total = elapsed(t0)
    return result


async def classify(
    client: AsyncClient, args: argparse.Namespace, user_msg: str, reply_so_far: str, sentence: str, t0: float
) -> dict:
    started = elapsed(t0)
    resp = await client.chat(
        model=args.model,
        messages=[
            {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Viewer message: {user_msg}\n"
                    f"Streamer so far: {reply_so_far or '(nothing yet)'}\n"
                    f"SENTENCE: {sentence}"
                ),
            },
        ],
        format=CLASSIFIER_SCHEMA,
        options={"temperature": 0, "num_predict": 80},
    )
    finished = elapsed(t0)
    verdict: dict = {"started": started, "finished": finished, "latency": round(finished - started, 3)}
    try:
        parsed = json.loads(resp.message.content)
        verdict.update(safe=bool(parsed["safe"]), reason=str(parsed["reason"]), valid_json=True)
    except (json.JSONDecodeError, KeyError, TypeError):
        verdict.update(safe=None, reason=resp.message.content, valid_json=False)
    return verdict


async def replace(client: AsyncClient, args: argparse.Namespace, user_msg: str, reply_so_far: str) -> dict:
    t0 = time.perf_counter()
    resp = await client.chat(
        model=args.model,
        messages=[
            {"role": "system", "content": REPLACER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Viewer message: {user_msg}\n"
                    f"What you said so far: {reply_so_far or '(nothing yet)'}\n"
                    "Block reason: the next sentence contained a prohibited word."
                ),
            },
        ],
        options={"temperature": 0.7, "num_predict": 60},
    )
    return {"latency": elapsed(t0), "text": resp.message.content.strip()}


async def pipeline(client: AsyncClient, args: argparse.Namespace, user_msg: str) -> dict:
    """The real flow: the reply keeps streaming while a worker classifies each sentence in order."""
    queue: asyncio.Queue[tuple[str, float] | None] = asyncio.Queue()
    verdicts: list[dict] = []
    t0 = time.perf_counter()

    async def on_sentence(sentence: str, t_ready: float) -> None:
        queue.put_nowait((sentence, t_ready))

    async def producer() -> StreamResult:
        try:
            return await stream_reply(client, args, user_msg, t0, on_sentence)
        finally:
            queue.put_nowait(None)

    async def filter_worker() -> None:
        reply_so_far = ""
        while (item := await queue.get()) is not None:
            sentence, t_ready = item
            verdict = await classify(client, args, user_msg, reply_so_far, sentence, t0)
            verdicts.append({"sentence": sentence, "ready": t_ready, **verdict})
            reply_so_far = f"{reply_so_far} {sentence}".strip()

    async with asyncio.timeout(args.timeout):
        async with asyncio.TaskGroup() as tg:
            producer_task = tg.create_task(producer())
            tg.create_task(filter_worker())

    stream = producer_task.result()
    return {
        "stream": asdict(stream),
        "verdicts": verdicts,
        "first_sentence_ready": stream.first_sentence,
        "first_approved": verdicts[0]["finished"] if verdicts else None,
        "stream_end": stream.total,
        "last_approved": verdicts[-1]["finished"] if verdicts else None,
    }


def parallel_verdict(pipe: dict, solo_classifier_latency: float) -> str:
    """Did the first classification run alongside the reply stream, or wait for it to finish?

    With OLLAMA_NUM_PARALLEL=1 the first classification can only finish after the stream ends.
    The test is only conclusive when the stream kept running long enough after the classifier was
    sent for a parallel classification to finish first (1.5x its solo latency, to allow for slowdown).
    """
    if not pipe["verdicts"]:
        return "inconclusive"
    first = pipe["verdicts"][0]
    if pipe["stream_end"] - first["started"] < 1.5 * solo_classifier_latency:
        return "inconclusive"
    return "parallel" if first["finished"] < pipe["stream_end"] else "serialized"


def total_ram_gb() -> float | None:
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True)
            return round(int(out.stdout) / 1024**3, 1)
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="utf-8") as f:
                kb = int(f.readline().split()[1])
            return round(kb / 1024**2, 1)
        if sys.platform == "win32":

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong)
                    for name in (
                        "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                        "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual",
                    )
                ]

            status = MemoryStatus(dwLength=ctypes.sizeof(MemoryStatus))
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return round(status.ullTotalPhys / 1024**3, 1)
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    return None


def cpu_name() -> str:
    if sys.platform == "darwin":
        out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return platform.processor() or platform.machine()


async def environment_info(client: AsyncClient, args: argparse.Namespace) -> dict:
    async with httpx.AsyncClient() as http:
        version = (await http.get(f"{args.host}/api/version", timeout=10)).json().get("version")
    details = (await client.show(args.model)).details
    return {
        "label": args.label,
        "ollama_version": version,
        "model": args.model,
        "parameter_size": getattr(details, "parameter_size", None),
        "quantization": getattr(details, "quantization_level", None),
        "machine": platform.platform(),
        "cpu": cpu_name(),
        "ram_gb": total_ram_gb(),
        "num_predict": args.num_predict,
    }


async def loaded_models(client: AsyncClient) -> list[dict]:
    models = []
    for m in (await client.ps()).models:
        models.append(
            {
                "model": m.model,
                "size_gb": round((m.size or 0) / 1024**3, 2),
                "size_vram_gb": round((m.size_vram or 0) / 1024**3, 2),
                "context_length": getattr(m, "context_length", None),
            }
        )
    return models


def stats(values: list[float | None]) -> tuple[str, str, str]:
    clean = [v for v in values if v is not None]
    if not clean:
        return ("-", "-", "-")
    return (f"{statistics.median(clean):.2f}", f"{min(clean):.2f}", f"{max(clean):.2f}")


def summarize(results: dict) -> str:
    runs = results["runs"]
    env = results["env"]
    n = len(runs)
    rows = [
        ("Solo: time to first token (s)", [r["solo"]["ttft"] for r in runs]),
        ("Solo: time to first full sentence (s)", [r["solo"]["first_sentence"] for r in runs]),
        ("Solo: full reply (s)", [r["solo"]["total"] for r in runs]),
        ("Solo: generation speed (tok/s)", [r["solo"]["tokens_per_s"] for r in runs]),
        ("Classifier alone, one sentence (s)", [r["classifier_solo"]["latency"] for r in runs]),
        ("Pipeline: first sentence ready (s)", [r["pipeline"]["first_sentence_ready"] for r in runs]),
        ("**Pipeline: first sentence approved = TTS can start (s)**", [r["pipeline"]["first_approved"] for r in runs]),
        ("Pipeline: reply stream finished (s)", [r["pipeline"]["stream_end"] for r in runs]),
        ("Pipeline: last sentence approved (s)", [r["pipeline"]["last_approved"] for r in runs]),
        ("Pipeline: classifier latency per sentence (s)",
         [v["latency"] for r in runs for v in r["pipeline"]["verdicts"]]),
        ("Pipeline: generation speed while classifying (tok/s)",
         [r["pipeline"]["stream"]["tokens_per_s"] for r in runs]),
        ("Replacer, one sentence (s)", [r["replacer"]["latency"] for r in runs]),
    ]
    modes = [r["parallel"] for r in runs]
    tags = [r["solo"]["tag_valid"] for r in runs] + [r["pipeline"]["stream"]["tag_valid"] for r in runs]
    verdicts = [r["classifier_solo"] for r in runs] + [v for r in runs for v in r["pipeline"]["verdicts"]]

    lines = [
        f"## Spike A results: `{env['label']}`",
        "",
        f"- Machine: {env['cpu']}, {env['ram_gb']} GB RAM ({env['machine']})",
        f"- Ollama {env['ollama_version']}, model `{env['model']}` "
        f"({env['parameter_size']}, {env['quantization']}), num_predict={env['num_predict']}",
        f"- Model load time (warm-up): {results['warmup_load_s']} s",
        f"- Prompts: {n}",
        "",
        "| Metric | Median | Min | Max |",
        "|---|---|---|---|",
    ]
    lines += [f"| {name} | {' | '.join(stats(values))} |" for name, values in rows]
    lines += [
        "",
        f"- **Classifier vs. reply stream: {modes.count('parallel')} parallel, {modes.count('serialized')} "
        f"serialized, {modes.count('inconclusive')} inconclusive** (serialized = the classifier waited for the "
        "reply to finish, as with OLLAMA_NUM_PARALLEL=1; inconclusive = the reply ended too soon to tell)",
        f"- Emotion tag valid: {sum(tags)}/{len(tags)} replies",
        f"- Classifier returned valid JSON: {sum(bool(v['valid_json']) for v in verdicts)}/{len(verdicts)} calls",
        "",
        "| Loaded model | Size in memory (GB) | On GPU (GB) | Context length |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {m['model']} | {m['size_gb']} | {m['size_vram_gb']} | {m['context_length'] or '-'} |"
        for m in results["loaded_models"]
    ]
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    client = AsyncClient(host=args.host)
    try:
        available = {m.model for m in (await client.list()).models}
    except (httpx.ConnectError, ConnectionError):
        print(f"Cannot reach Ollama at {args.host}. Is it running?", file=sys.stderr)
        return 2
    if args.model not in available and f"{args.model}:latest" not in available:
        print(f"Model {args.model!r} is not pulled. Run: ollama pull {args.model}", file=sys.stderr)
        return 2

    results: dict = {"env": await environment_info(client, args), "runs": []}

    print(f"Loading {args.model} ...", flush=True)
    warmup = await client.chat(
        model=args.model, messages=[{"role": "user", "content": "Say OK."}], options={"num_predict": 1}
    )
    results["warmup_load_s"] = round((warmup.load_duration or 0) / 1e9, 2)

    for i, prompt in enumerate(PROMPTS[: args.prompts], start=1):
        print(f"[{i}/{args.prompts}] {prompt}", flush=True)
        # Different viewer names keep the solo and pipeline runs from reusing each other's prompt cache.
        solo_msg, pipe_msg = f"Viewer Aki says: {prompt}", f"Viewer Ren says: {prompt}"
        solo = await stream_reply(client, args, solo_msg, time.perf_counter())
        first = solo.sentences[0]["text"] if solo.sentences else solo.text
        classifier_solo = await classify(client, args, solo_msg, "", first, time.perf_counter())
        pipe = await pipeline(client, args, pipe_msg)
        replacer = await replace(client, args, solo_msg, first)
        mode = parallel_verdict(pipe, classifier_solo["latency"])
        results["runs"].append(
            {"prompt": prompt, "solo": asdict(solo), "classifier_solo": classifier_solo,
             "pipeline": pipe, "replacer": replacer, "parallel": mode}
        )
        print(
            f"    solo reply {solo.total:.1f}s @ {solo.tokens_per_s} tok/s | first approved "
            f"{pipe['first_approved']}s, stream end {pipe['stream_end']}s, classifier {mode}",
            flush=True,
        )

    results["loaded_models"] = await loaded_models(client)
    summary = summarize(results)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.label}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / f"{args.label}.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)
    print(f"Saved to {out_dir / args.label}.json and .md")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True, help="name for this run, e.g. parallel-1")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--prompts", type=int, default=len(PROMPTS), choices=range(1, len(PROMPTS) + 1))
    parser.add_argument("--num-predict", type=int, default=150)
    parser.add_argument("--timeout", type=float, default=300, help="seconds allowed per pipeline run")
    parser.add_argument("--out-dir", default=str(Path(__file__).parent / "results"))
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except ResponseError as e:
        print(f"Ollama error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
