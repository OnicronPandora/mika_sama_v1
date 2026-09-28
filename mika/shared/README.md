# mika-shared

The contracts both machines use: enums, payloads and every WebSocket event
([implementation plan, section 5](../../docs/implementation_plan.md#5-event-contracts)).
The frontend's TypeScript types are generated from these models.

## Install (Mac and Acer, inside the project's `.conda` env)

```bash
pip install -e "mika/shared[dev]"
```

## Test

```bash
pytest mika/shared
```

## After changing a model

Regenerate the frontend types, then commit both:

```bash
python -m mika_shared.codegen_ts --write
```

`tests/test_codegen_ts.py` fails if `mika/frontend/src/types/events.ts` is out of date.

## Usage

```python
from mika_shared.events import TurnStart, parse_runtime_client_event
from mika_shared.enums import Emotion

await websocket.send_text(TurnStart(turn_id=turn_id, emotion=Emotion.HAPPY).model_dump_json())
event = parse_runtime_client_event(await websocket.receive_text())  # raises pydantic.ValidationError
```
