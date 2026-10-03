"""Heuristic project health report. NOT a professional security audit."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List

from ..logging_setup import redact
from .index import ProjectIndex
from .project import detect_project
from .workspace import SKIP_DIRS

DISCLAIMER = "Heuristic findings only — this is not a professional security audit."


@dataclass
class Finding:
    category: str
    severity: str  # info | low | medium | high
    where: str
    message: str


@dataclass
class HealthReport:
    findings: List[Finding] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    def by_category(self, c: str) -> List[Finding]:
        return [f for f in self.findings if f.category == c]


def analyze(root: str) -> HealthReport:
    rep = HealthReport()
    info = detect_project(root)
    idx = ProjectIndex(root).build()
    for path, line, text in idx.todos():
        rep.findings.append(Finding("todo", "info", f"{path}:{line}", text))
    for f in idx.files.values():
        if f.syntax_error:
            rep.findings.append(Finding("bug", "high", f.path, f"syntax error: {f.syntax_error}"))
        if f.lines > 1500:
            rep.findings.append(Finding("quality", "low", f.path, f"very large file ({f.lines} lines)"))
    seen = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            fp = os.path.join(dp, fn)
            rel = os.path.relpath(fp, root)
            try:
                if os.path.getsize(fp) > 300_000:
                    continue
                text = open(fp, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if redact(text) != text and fn != "test_agent.py":
                rep.findings.append(Finding("security", "high", rel, "possible hard-coded secret"))
            if fn.endswith(".py"):
                for m in re.finditer(r"^\s*except\s*:\s*$", text, re.M):
                    rep.findings.append(Finding("quality", "low", f"{rel}:{text.count(chr(10), 0, m.start()) + 1}", "bare except"))
                if re.search(r"\beval\(|\bexec\(|shell\s*=\s*True|pickle\.loads", text):
                    rep.findings.append(Finding("security", "medium", rel, "risky call (eval/exec/shell=True/pickle)"))
                for i in range(0, len(text.splitlines()) - 8, 8):  # crude duplicate-block detector
                    block = "\n".join(l.strip() for l in text.splitlines()[i:i + 8])
                    if len(block) > 160:
                        seen.setdefault(block, []).append(f"{rel}:{i + 1}")
    for locs in seen.values():
        if len(locs) > 1:
            rep.findings.append(Finding("duplicate", "low", ", ".join(locs[:3]), "duplicated code block"))
    if not info.has_tests:
        rep.findings.append(Finding("tests", "medium", ".", "no tests directory found"))
    if "Python" in info.languages and not any(d for d in info.dependencies if "==" in d) and info.dependencies:
        rep.findings.append(Finding("dependency", "low", "requirements.txt", "dependencies are not version-pinned"))
    if not os.path.exists(os.path.join(root, ".gitignore")) and info.git_repo:
        rep.findings.append(Finding("security", "low", ".", "no .gitignore (risk of committing secrets)"))
    return rep
