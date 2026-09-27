from pathlib import Path

from mika_shared import codegen_ts, events

FRONTEND_TYPES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "events.ts"


def test_frontend_types_are_up_to_date():
    assert FRONTEND_TYPES.read_text(encoding="utf-8") == codegen_ts.generate(), (
        "mika/frontend/src/types/events.ts is out of date. Run: python -m mika_shared.codegen_ts --write"
    )


def test_every_event_becomes_an_interface_with_its_type_literal():
    code = codegen_ts.generate()
    for _, _, union in codegen_ts.CHANNELS:
        for model in events.event_types(union):
            assert f"export interface {model.__name__} {{\n  type: '{model.model_fields['type'].default}';" in code


def test_field_mappings():
    code = codegen_ts.generate()
    assert "export type Emotion = 'happy' | 'sad' | 'confused' | 'angry' | 'neutral';" in code
    assert "  last_seq: number | null;" in code  # required but nullable
    assert "  turn_id?: string | null;" in code  # TurnError: optional, may be null
    assert "  detail?: string | null;" in code
    assert "  sample_rate: number;" in code
    assert "export type ChatServerEvent = EmotionUpdate | AudioChunk | ChatTurnEnd | Transcript;" in code
