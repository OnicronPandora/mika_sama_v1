"""The latency bench runs end to end (here on the scripted LLM; on the Mac, on llama3.1:8b)."""

import argparse

from fakes import FakeEngine, verdict

from app.config import LLMSettings
from app.turn.bench import LABELED, Recorder, print_summary, run_mode


async def test_the_bench_runs_a_mode_end_to_end(capsys):
    turns = 2
    engine = FakeEngine(
        *[verdict(True)] * (2 * turns + len(LABELED)),
        replies=[["[happy] Hi Pandora! Welcome back."] for _ in range(turns)],
    )
    engine.settings = LLMSettings(seed=7)
    result = await run_mode("shared", engine, Recorder(), argparse.Namespace(turns=turns, no_verdicts=False, timeout=None))
    print_summary([result])
    out = capsys.readouterr().out
    assert len(result.turns) == turns and len(result.verdicts) == len(LABELED)
    assert all(len(turn.sentences) == 2 and turn.end_at is not None for turn in result.turns)
    assert "=== shared mode ===" in out and "labeled verdicts correct" in out
