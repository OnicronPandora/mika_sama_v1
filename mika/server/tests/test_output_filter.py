"""The policy engine end to end, with a scripted fake LLM (plan, Phase 4 "done when")."""

import random

import pytest
from fakes import FakeEngine, verdict

from app.config import FilterSettings
from app.filter.ai_classifier import FilterPolicy, SafetyClassifier
from app.filter.context import TurnContext
from app.filter.hard_rules import ProhibitedWords
from app.filter.policy import OutputFilter, build_output_filter, load_fallbacks
from app.filter.replacer import Replacer
from app.llm.engine import LLMEngine
from app.config import LLMSettings
from app.personality.engine import load_personality
from mika_shared.enums import FilterAction

FALLBACK = "Hmm, let's talk about something else!"
CONTEXT = TurnContext(user_message="Hi Mika!")
SETTINGS = FilterSettings(classifier_timeout=0.1, replacer_timeout=0.1)


def make_filter(engine: FakeEngine) -> OutputFilter:
    return OutputFilter(
        words=ProhibitedWords(["darn"]),
        classifier=SafetyClassifier(engine, FilterPolicy(allowed=["a"], unsafe=["b"]), SETTINGS, streamer="Mika"),
        replacer=Replacer(engine, SETTINGS, persona="Mika, AI VTuber"),
        fallbacks=[FALLBACK],
        filtered_prefix="Filtered!",
        rng=random.Random(0),
    )


async def test_allow():
    engine = FakeEngine(verdict(True))
    result = await make_filter(engine).check("Hi everyone!", CONTEXT)
    assert (result.action, result.filter_response, result.reason) == (FilterAction.ALLOW, None, None)
    assert len(engine.calls) == 1


async def test_replace_with_an_llm_line_that_passes_its_check():
    engine = FakeEngine(verdict(False, "sexual content"), "Anyway, games?", verdict(True))
    result = await make_filter(engine).check("Something spicy.", CONTEXT)
    assert result.action is FilterAction.REPLACE
    assert result.filter_response == "Filtered! Anyway, games?"
    assert result.reason == "classifier: sexual content"
    assert engine.classifier_calls[1].messages[1]["content"].endswith("SENTENCE: Anyway, games?")  # re-checked


async def test_replace_with_an_unsafe_replacement_uses_the_fallback():
    engine = FakeEngine(verdict(False, "threat"), "Another bad line.", verdict(False, "still bad"))
    result = await make_filter(engine).check("Something bad.", CONTEXT)
    assert (result.action, result.filter_response) == (FilterAction.REPLACE, f"Filtered! {FALLBACK}")


async def test_replace_rejects_a_replacement_with_a_prohibited_word():
    engine = FakeEngine(verdict(False), "Oh darn, never mind.")  # no classifier call needed for the re-check
    result = await make_filter(engine).check("Something bad.", CONTEXT)
    assert result.filter_response == f"Filtered! {FALLBACK}"
    assert len(engine.calls) == 2


@pytest.mark.parametrize("answer", [1.0, "not json", ConnectionError("down")])
async def test_classifier_failure_replaces_with_the_fallback_without_more_llm_calls(answer):
    engine = FakeEngine(answer)
    result = await make_filter(engine).check("Anything.", CONTEXT)
    assert (result.action, result.filter_response) == (FilterAction.REPLACE, f"Filtered! {FALLBACK}")
    assert len(engine.calls) == 1


async def test_block_with_an_llm_rewrite_that_passes_its_check():
    engine = FakeEngine("Let's keep it friendly!", verdict(True))
    result = await make_filter(engine).check("Oh darn it.", CONTEXT)
    assert result.action is FilterAction.BLOCK
    assert result.filter_response == "Let's keep it friendly!"
    assert result.reason == "prohibited word: darn"
    assert engine.calls[0].json_schema is None  # the blocked sentence never went to the classifier


async def test_block_with_an_unsafe_rewrite_uses_the_fallback():
    engine = FakeEngine("Darn, sorry!")  # the rewrite contains a prohibited word too
    result = await make_filter(engine).check("Oh darn it.", CONTEXT)
    assert (result.action, result.filter_response) == (FilterAction.BLOCK, FALLBACK)


async def test_block_when_the_replacer_times_out_uses_the_fallback():
    result = await make_filter(FakeEngine(1.0)).check("Oh darn it.", CONTEXT)
    assert (result.action, result.filter_response) == (FilterAction.BLOCK, FALLBACK)


def test_needs_a_fallback_line():
    engine = FakeEngine()
    with pytest.raises(ValueError):
        OutputFilter(
            words=ProhibitedWords([]),
            classifier=SafetyClassifier(engine, FilterPolicy(allowed=[], unsafe=[]), SETTINGS, streamer="Mika"),
            replacer=Replacer(engine, SETTINGS, persona="Mika"),
            fallbacks=[],
            filtered_prefix="Filtered!",
        )


def test_the_shipped_data_files_build_a_filter():
    assert load_fallbacks()
    output_filter = build_output_filter(LLMEngine(LLMSettings()), load_personality(), FilterSettings())
    assert output_filter.filtered_prefix == "Filtered!"
    assert "Mika-sama" in output_filter.classifier.system_prompt
