"""The latency bench runs end to end (here on the scripted LLM; on the Mac, on llama3.1:8b)."""

import argparse

from fakes import FakeEngine, verdict

from app.config import LLMSettings
from app.turn.bench import LABELED, Recorder, print_summary, run_bench


async def test_the_bench_runs_end_to_end(capsys):
    turns = 2
    engine = FakeEngine(
        *[verdict(True)] * (2 * turns + len(LABELED)),
        replies=[["[happy] Hi Pandora! Welcome back."] for _ in range(turns)],
    )
    engine.settings = LLMSettings(seed=7)
    result = await run_bench(engine, Recorder(), argparse.Namespace(turns=turns, no_verdicts=False, timeout=None))
    print_summary(result)
    out = capsys.readouterr().out
    assert len(result.turns) == turns and len(result.verdicts) == len(LABELED)
    assert all(len(turn.sentences) == 2 and turn.end_at is not None for turn in result.turns)
    assert "first sentence approved" in out and "labeled verdicts correct" in out


async def test_the_bench_shows_why_a_sentence_was_filtered(capsys):
    engine = FakeEngine(verdict(False, "personal information"), "Anyway, games?", verdict(True), replies=[["[happy] Secret."]])
    engine.settings = LLMSettings(seed=7)
    await run_bench(engine, Recorder(), argparse.Namespace(turns=1, no_verdicts=True, timeout=None))
    out = capsys.readouterr().out
    assert "Filtered because: classifier: personal information" in out
    assert "Mika's original reply: [happy] Secret." in out
