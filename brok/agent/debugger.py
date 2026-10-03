"""AI debugger: parse errors, gather source context, build the analysis→patch→verify prompt."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

_FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
_LAST = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt))\s*:?\s*(.*)$", re.M)


@dataclass
class Frame:
    file: str
    line: int
    func: str


@dataclass
class ParsedError:
    error_type: str
    message: str
    frames: List[Frame]


def parse_traceback(text: str) -> ParsedError:
    frames = [Frame(f, int(n), fn) for f, n, fn in _FRAME.findall(text)]
    last = _LAST.findall(text)
    et, msg = last[-1] if last else ("", "")
    return ParsedError(et, msg.strip(), frames)


def source_context(root: str, err: ParsedError, radius: int = 6, max_frames: int = 4) -> str:
    """Code around the innermost project frames (files outside root are skipped)."""
    root = os.path.realpath(root)
    blocks: List[str] = []
    for fr in reversed(err.frames):
        full = os.path.realpath(fr.file if os.path.isabs(fr.file) else os.path.join(root, fr.file))
        if not full.startswith(root + os.sep) or not os.path.isfile(full):
            continue
        lines = open(full, encoding="utf-8", errors="replace").read().splitlines()
        lo, hi = max(0, fr.line - 1 - radius), min(len(lines), fr.line + radius)
        body = "\n".join(f"{'>>' if i + 1 == fr.line else '  '} {i + 1}: {lines[i]}" for i in range(lo, hi))
        blocks.append(f"# {os.path.relpath(full, root)} (in {fr.func})\n{body}")
        if len(blocks) >= max_frames:
            break
    return "\n\n".join(blocks)


def debug_prompt(error_text: str, root: str, logs: str = "", language: str = "fa") -> str:
    err = parse_traceback(error_text)
    ctx = source_context(root, err)
    lang = "Explain in Persian; keep code/identifiers in English." if language == "fa" else ""
    return (
        "Debug this error. Pipeline: 1) locate the likely cause 2) explain it simply 3) propose a minimal fix "
        "4) apply it with write_file (diff is shown to the user) 5) run_tests to verify 6) report the result. "
        f"{lang}\n\nERROR ({err.error_type}): {err.message}\n\n```\n{error_text[-4000:]}\n```\n\n"
        f"RELEVANT SOURCE:\n{ctx or '(none found inside the project)'}\n" + (f"\nLOGS:\n{logs[-2000:]}\n" if logs else "")
    )
