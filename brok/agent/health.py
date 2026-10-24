"""Heuristic project health report. NOT a professional security audit."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field

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
    findings: list[Finding] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    def by_category(self, c: str) -> list[Finding]:
        return [f for f in self.findings if f.category == c]


def _is_git_ignored(root: str, rel: str) -> bool:
    try:
        r = subprocess.run(["git", "check-ignore", "-q", "--", rel], cwd=root, capture_output=True, timeout=10)
        if r.returncode in (0, 1):
            return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        pass
    try:  # not a git repo / no git: fall back to a literal look at .gitignore
        with open(os.path.join(root, ".gitignore"), encoding="utf-8", errors="ignore") as fh:
            return any(ln.strip() in (".env", ".env*", "*.env", "/.env", rel) for ln in fh)
    except OSError:
        return False


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
    seen: dict[str, list[str]] = {}
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
            if fn == ".env" or (fn.startswith(".env.") and not fn.endswith((".example", ".sample", ".template"))):
                if not _is_git_ignored(root, rel):
                    rep.findings.append(Finding("security", "high", rel, "secrets file is not ignored by git"))
            elif redact(text) != text:
                rep.findings.append(Finding("security", "high", rel, "possible hard-coded secret"))
            if fn.endswith(".py"):
                for m in re.finditer(r"^\s*except\s*:\s*$", text, re.M):
                    rep.findings.append(
                        Finding("quality", "low", f"{rel}:{text.count(chr(10), 0, m.start()) + 1}", "bare except")
                    )
                if re.search(r"\beval\(|\bexec\(|shell\s*=\s*True|pickle\.loads", text):
                    rep.findings.append(Finding("security", "medium", rel, "risky call (eval/exec/shell=True/pickle)"))
                src_lines = text.splitlines()
                for i in range(0, len(src_lines) - 7, 8):  # crude duplicate-block detector (8-line windows)
                    block = "\n".join(ln.strip() for ln in src_lines[i : i + 8])
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
