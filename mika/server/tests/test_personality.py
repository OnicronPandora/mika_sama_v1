import pytest
from pydantic import ValidationError

from app.personality.engine import REPLY_RULES, Personality, build_system_prompt, load_personality
from mika_shared.enums import Emotion

MIKA = Personality(name="Mika", role="VTuber", core_identity="You are Mika.", guidelines=["Be kind."])


def test_the_shipped_personality_file_is_valid():
    personality = load_personality()
    assert personality.name == "Mika-sama"
    assert personality.guidelines


def test_prompt_layers_come_in_order():
    prompt = build_system_prompt(MIKA, traits=["Loves rainy days", "  "], stream_rules="Stream rules: be nice.")
    parts = ("You are Mika.", "- Be kind.", "- Loves rainy days", "Stream rules: be nice.", "How to reply:")
    order = [prompt.index(part) for part in parts]
    assert order == sorted(order)
    assert "-   " not in prompt  # blank traits are dropped


def test_no_learned_traits_or_rules_sections_without_them():
    prompt = build_system_prompt(MIKA)
    assert "learned" not in prompt and "Stream rules" not in prompt


def test_reply_rules_list_every_emotion_tag():
    for emotion in Emotion:
        assert f"[{emotion.value}]" in REPLY_RULES


def test_a_typo_in_the_file_is_an_error(tmp_path):
    path = tmp_path / "personality.yaml"
    path.write_text("name: x\nrole: y\ncore_identity: z\nguideline:\n  - a\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_personality(path)
