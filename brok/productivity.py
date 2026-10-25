"""Productivity tools: safe calculator and notes."""

from __future__ import annotations

import ast
import math
import operator as op
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .agent.tools import Confirm, Risk, ToolError, ToolRegistry, ToolSpec

_OPS: dict[type, Callable[..., Any]] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}
MAX_RESULT_BITS = 100_000  # ~30k digits: keeps a model-driven `((10**1000)**1000)**1000` from eating all memory
MAX_NOTE_CHARS = 2000
_NAMES: dict[str, Any] = {
    "pi": math.pi,
    "e": math.e,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "abs": abs,
    "round": round,
}


def calculate(expression: str) -> str:
    """Evaluate arithmetic only (no names/attributes/imports): safe against code injection."""

    def bounded(value: Any) -> Any:
        # The tool never asks for approval, so its cost must be bounded as well: cap integer size after every step
        # (the exponent limit alone does not stop repeated squaring or big multiplications).
        if isinstance(value, int) and value.bit_length() > MAX_RESULT_BITS:
            raise ToolError("result too large")
        return value

    def ev(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 1000:
                raise ToolError("exponent too large")
            return bounded(_OPS[type(n.op)](ev(n.left), ev(n.right)))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Name) and n.id in _NAMES and not callable(_NAMES[n.id]):
            return _NAMES[n.id]
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and callable(_NAMES.get(n.func.id))
            and not n.keywords
        ):
            return bounded(_NAMES[n.func.id](*[ev(a) for a in n.args]))
        raise ToolError("unsupported expression")

    try:
        return str(ev(ast.parse(expression.strip(), mode="eval")))
    except (SyntaxError, ZeroDivisionError, OverflowError, ValueError, RecursionError, MemoryError) as exc:
        raise ToolError(f"cannot calculate: {exc}")


class Notes:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def add(self, text: str) -> str:
        # One note = one line: join on EVERY line break splitlines() knows (\r, \x0b, \x0c, U+2028 ...), not only \n.
        line = " ".join(text.strip().splitlines())
        if not line:
            raise ToolError("the note is empty")
        if len(line) > MAX_NOTE_CHARS:
            raise ToolError(f"note too long ({len(line)} > {MAX_NOTE_CHARS} characters)")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return "note saved"

    def list(self) -> str:
        try:
            lines = self.path.read_text(encoding="utf-8").split("\n")  # not splitlines(): must match add()
        except OSError:
            return "no notes"
        if lines and lines[-1] == "":
            lines.pop()
        return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)) or "no notes"


def register_productivity_tools(reg: ToolRegistry, notes: Notes) -> None:
    S = {"type": "string"}
    reg.register(
        ToolSpec(
            "calculate",
            "Evaluate an arithmetic expression.",
            {"type": "object", "properties": {"expression": S}, "required": ["expression"]},
            Risk.LOW,
            Confirm.NEVER,
            calculate,
        )
    )
    reg.register(
        ToolSpec(
            "add_note",
            "Save a note.",
            {"type": "object", "properties": {"text": S}, "required": ["text"]},
            Risk.MEDIUM,
            Confirm.CONFIGURABLE,
            notes.add,
        )
    )
    reg.register(
        ToolSpec(
            "list_notes", "List saved notes.", {"type": "object", "properties": {}}, Risk.LOW, Confirm.NEVER, notes.list
        )
    )
