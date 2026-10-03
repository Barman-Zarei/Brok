from __future__ import annotations

import difflib


def unified_diff(before: str, after: str, path: str = "file") -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{path}", f"b/{path}"))
