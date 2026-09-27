"""Spike B: GenieTTS speed on the Acer (Phase 0 of docs/implementation_plan.md).

Question: can GenieTTS synthesize Mika's sentences faster than real time on the Acer's CPU?
A real-time factor (RTF = synthesis time / audio length) below 1.0 means it can keep up.

Run it on the Acer from the repo root:

    python spikes/spike_b_tts/spike_b_tts.py --label acer

Each run prints a Markdown summary, writes results/<label>.json and results/<label>.md, and
saves the generated audio to out/ so you can listen to it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import sys
import time
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = REPO_ROOT / "others" / "voice"

SAMPLE_RATE = 32000  # GenieTTS output: 16-bit mono PCM at 32 kHz
BYTES_PER_SAMPLE = 2

SENTENCES = [
    "Hi everyone!",
    "Welcome back to the stream.",
    "Oh no, did your cat really knock the coffee off the desk again?",
    "The sky looks blue because tiny particles in the air scatter blue light more than red light.",
    "Hmm, I'm a little confused, can you say that one more time?",
    "People who are mean in chat make me sad, but I know most of you are really kind.",
    "Okay, let's play one more round and then we'll take a short break.",
    "Thank you so much for watching today, I had a lot of fun with all of you, see you next time!",
]


def audio_seconds(pcm: bytes) -> float:
    return len(pcm) / BYTES_PER_SAMPLE / SAMPLE_RATE


def save_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(BYTES_PER_SAMPLE)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


async def synthesize(genie, text: str) -> tuple[bytes, float, float]:
    """Return (pcm, seconds to first chunk, seconds total) for one sentence."""
    t0 = time.perf_counter()
    first_chunk = None
    chunks = []
    async for chunk in genie.tts_async(character_name="mika", text=text, play=False, split_sentence=False):
        if first_chunk is None:
            first_chunk = time.perf_counter() - t0
        chunks.append(chunk)
    return b"".join(chunks), first_chunk or 0.0, time.perf_counter() - t0


async def run(args: argparse.Namespace) -> int:
    genie_data = Path(args.genie_data)
    if not genie_data.is_dir():
        print(
            f"GenieData not found at {genie_data}.\n"
            "Copy an existing GenieData folder there, or pass --genie-data <path>.",
            file=sys.stderr,
        )
        return 2
    # genie_tts reads GENIE_DATA_DIR at import time and prompts on stdin if it is missing.
    os.environ["GENIE_DATA_DIR"] = str(genie_data)
    import genie_tts as genie
    import onnxruntime

    ref_wav = VOICE_DIR / "ref_data" / "55.wav"
    ref_text = (VOICE_DIR / "ref_data" / "55.txt").read_text(encoding="utf-8").strip()

    t0 = time.perf_counter()
    genie.load_character(character_name="mika", onnx_model_dir=VOICE_DIR / "mikav3_onnx_model", language="en")
    genie.set_reference_audio(character_name="mika", audio_path=ref_wav, audio_text=ref_text, language="en")
    load_s = time.perf_counter() - t0

    # The first synthesis also processes the reference audio, so it is timed separately.
    _, _, warmup_s = await synthesize(genie, "Warming up.")

    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(exist_ok=True)
    rows = []
    for i, text in enumerate(SENTENCES, start=1):
        pcm, first_chunk_s, synth_s = await synthesize(genie, text)
        audio_s = audio_seconds(pcm)
        rtf = synth_s / audio_s if audio_s else None
        save_wav(out_dir / f"{args.label}_{i:02d}.wav", pcm)
        rows.append(
            {"text": text, "words": len(text.split()), "audio_s": round(audio_s, 2),
             "synth_s": round(synth_s, 2), "first_chunk_s": round(first_chunk_s, 2),
             "rtf": round(rtf, 3) if rtf else None}
        )
        print(f"[{i}/{len(SENTENCES)}] {audio_s:5.2f}s audio in {synth_s:5.2f}s (RTF {rtf:.2f}) {text}", flush=True)

    env = {
        "label": args.label,
        "machine": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "onnxruntime": onnxruntime.__version__,
        "providers": onnxruntime.get_available_providers(),
        "load_s": round(load_s, 2),
        "warmup_s": round(warmup_s, 2),
    }
    results = {"env": env, "sentences": rows}
    summary = summarize(results)

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / f"{args.label}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (results_dir / f"{args.label}.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)
    print(f"Audio saved to {out_dir}")
    return 0


def summarize(results: dict) -> str:
    env, rows = results["env"], results["sentences"]
    rtfs = [r["rtf"] for r in rows if r["rtf"]]
    lines = [
        f"## Spike B results: `{env['label']}`",
        "",
        f"- Machine: {env['cpu']} ({env['logical_cpus']} logical CPUs), {env['machine']}",
        f"- Python {env['python']}, onnxruntime {env['onnxruntime']}, providers: {', '.join(env['providers'])}",
        f"- Load model + reference audio: {env['load_s']} s; first synthesis (warm-up): {env['warmup_s']} s",
        f"- **Median real-time factor: {statistics.median(rtfs):.2f}** (max {max(rtfs):.2f}; below 1.0 keeps up)",
        "",
        "| # | Words | Audio (s) | Synthesis (s) | RTF | Sentence |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {i} | {r['words']} | {r['audio_s']} | {r['synth_s']} | {r['rtf']} | {r['text']} |"
        for i, r in enumerate(rows, start=1)
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", default="acer")
    parser.add_argument("--genie-data", default=str(VOICE_DIR / "GenieData"))
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
