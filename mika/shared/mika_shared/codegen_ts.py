"""Generate the frontend's TypeScript event types from the shared models.

    python -m mika_shared.codegen_ts            # print the TypeScript
    python -m mika_shared.codegen_ts --write    # write mika/frontend/src/types/events.ts

The Python models are the source of truth. tests/test_codegen_ts.py fails when the committed
TypeScript file is out of date. Writing needs the editable install (pip install -e mika/shared).
"""

import argparse
import inspect
import sys
import types
import typing
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from . import enums, events

FRONTEND_TYPES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "events.ts"

HEADER = "// Generated from mika/shared by `python -m mika_shared.codegen_ts --write`. Do not edit by hand."

ENUMS = (
    enums.Emotion,
    enums.Intent,
    enums.FilterAction,
    enums.MessageSource,
    enums.TranscriptRole,
    enums.ClientComponent,
    enums.ComponentState,
)

CHANNELS = (
    ("RuntimeClientEvent", "/ws/runtime: Acer -> Mac", events.RuntimeClientEvent),
    ("RuntimeServerEvent", "/ws/runtime: Mac -> Acer", events.RuntimeServerEvent),
    ("ChatClientEvent", "/ws/chat: browser -> Acer", events.ChatClientEvent),
    ("ChatServerEvent", "/ws/chat: Acer -> browser", events.ChatServerEvent),
)


def ts_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    raise TypeError(f"No TypeScript literal for {value!r}")


def ts_type(tp: object) -> str:
    origin = typing.get_origin(tp)
    if origin is typing.Annotated:
        return ts_type(typing.get_args(tp)[0])
    if origin is typing.Literal:
        return " | ".join(ts_literal(v) for v in typing.get_args(tp))
    if origin in (typing.Union, types.UnionType):
        return " | ".join(ts_type(arg) for arg in typing.get_args(tp))
    if origin is list:
        item = ts_type(typing.get_args(tp)[0])
        return f"({item})[]" if " | " in item else f"{item}[]"
    if tp is type(None):
        return "null"
    if inspect.isclass(tp) and issubclass(tp, (Enum, BaseModel)):
        return tp.__name__
    if tp is str:
        return "string"
    if tp is bool:
        return "boolean"
    if tp in (int, float):
        return "number"
    raise TypeError(f"No TypeScript type for {tp!r}")


def doc_comment(text: str | None, indent: str = "") -> list[str]:
    if not text:
        return []
    first_paragraph = inspect.cleandoc(text).split("\n\n")[0].replace("\n", " ")
    return [f"{indent}/** {first_paragraph} */"]


def ts_enum(enum_cls: type[Enum]) -> str:
    values = " | ".join(ts_literal(member.value) for member in enum_cls)
    return "\n".join([*doc_comment(enum_cls.__doc__), f"export type {enum_cls.__name__} = {values};"])


def ts_interface(model: type[BaseModel]) -> str:
    lines = [*doc_comment(model.__doc__), f"export interface {model.__name__} {{"]
    # The discriminator goes first; the rest keep their declaration order.
    for name, info in sorted(model.model_fields.items(), key=lambda item: item[0] != "type"):
        optional = name != "type" and not info.is_required()
        lines += doc_comment(info.description, indent="  ")
        lines.append(f"  {name}{'?' if optional else ''}: {ts_type(info.annotation)};")
    lines.append("}")
    return "\n".join(lines)


def generate() -> str:
    sections = [HEADER, "// ---- Enums ----", *(ts_enum(e) for e in ENUMS)]
    for _, title, union in CHANNELS:
        sections.append(f"// ---- {title} ----")
        sections += [ts_interface(model) for model in events.event_types(union)]
    sections.append("// ---- One union per channel direction ----")
    for name, title, union in CHANNELS:
        members = " | ".join(model.__name__ for model in events.event_types(union))
        sections.append(f"/** {title} */\nexport type {name} = {members};")
    return "\n\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help=f"write {FRONTEND_TYPES} instead of printing")
    args = parser.parse_args(argv)
    code = generate()
    if args.write:
        FRONTEND_TYPES.parent.mkdir(parents=True, exist_ok=True)
        FRONTEND_TYPES.write_text(code, encoding="utf-8", newline="\n")
        print(f"Wrote {FRONTEND_TYPES}")
    else:
        sys.stdout.write(code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
