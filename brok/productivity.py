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

    def ev(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 1000:
                raise ToolError("exponent too large")
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
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
            return _NAMES[n.func.id](*[ev(a) for a in n.args])
        raise ToolError("unsupported expression")

    try:
        return str(ev(ast.parse(expression.strip(), mode="eval")))
    except (SyntaxError, ZeroDivisionError, OverflowError, ValueError) as exc:
        raise ToolError(f"cannot calculate: {exc}")


class Notes:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def add(self, text: str) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(text.strip().replace("\n", " ") + "\n")
        return "note saved"

    def list(self) -> str:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return "no notes"
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
