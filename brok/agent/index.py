"""Lightweight codebase index: symbols, imports, TODOs; targeted retrieval (no whole-repo prompts)."""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field

from .workspace import SKIP_DIRS

CODE_EXT = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".dart",
    ".java",
    ".cs",
    ".cpp",
    ".cc",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".html",
    ".css",
    ".md",
}
_SYM_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:(?:public|private|static|abstract)\s+)*"
    r"(?:class|function|def|fn|func|interface)\s+([A-Za-z_]\w*)",
    re.M,
)
_TODO_RE = re.compile(r"(?:#|//|/\*|<!--)\s*(TODO|FIXME|XXX|HACK)\b[:\s]*(.*)")
MAX_FILE = 400_000


@dataclass
class Symbol:
    name: str
    kind: str
    file: str
    line: int


@dataclass
class FileEntry:
    path: str
    lines: int
    imports: list[str] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    todos: list[tuple[int, str]] = field(default_factory=list)
    syntax_error: str = ""


class ProjectIndex:
    def __init__(self, root: str) -> None:
        self.root = root
        self.files: dict[str, FileEntry] = {}

    def build(self) -> ProjectIndex:
        self.files.clear()
        for dp, dns, fns in os.walk(self.root):
            dns[:] = [d for d in sorted(dns) if d not in SKIP_DIRS]
            for fn in sorted(fns):
                if os.path.splitext(fn)[1].lower() in CODE_EXT:
                    self._index(os.path.join(dp, fn))
        return self

    def _index(self, full: str) -> None:
        rel = os.path.relpath(full, self.root)
        try:
            if os.path.getsize(full) > MAX_FILE:
                return
            text = open(full, encoding="utf-8", errors="replace").read()
        except OSError:
            return
        entry = FileEntry(rel, text.count("\n") + 1)
        for i, line in enumerate(text.splitlines(), 1):
            m = _TODO_RE.search(line)
            if m:
                entry.todos.append((i, f"{m.group(1)} {m.group(2)}".strip()))
        if full.endswith(".py"):
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        entry.symbols.append(Symbol(node.name, "function", rel, node.lineno))
                    elif isinstance(node, ast.ClassDef):
                        entry.symbols.append(Symbol(node.name, "class", rel, node.lineno))
                    elif isinstance(node, ast.Import):
                        entry.imports += [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        entry.imports.append(("." * node.level) + (node.module or ""))
            except (SyntaxError, ValueError) as exc:
                entry.syntax_error = str(exc)
        else:
            for m in _SYM_RE.finditer(text):
                entry.symbols.append(Symbol(m.group(1), "symbol", rel, text.count("\n", 0, m.start()) + 1))
        self.files[rel] = entry

    def symbols(self) -> list[Symbol]:
        return [s for f in self.files.values() for s in f.symbols]

    def todos(self) -> list[tuple[str, int, str]]:
        return [(f.path, ln, t) for f in self.files.values() for ln, t in f.todos]

    def find_symbol(self, query: str, limit: int = 20) -> list[Symbol]:
        q = query.lower()
        scored = []
        for s in self.symbols():
            n = s.name.lower()
            if n == q:
                scored.append((0, s))
            elif q in n:
                scored.append((1, s))
        return [s for _, s in sorted(scored, key=lambda t: (t[0], t[1].file, t[1].line))][:limit]

    def retrieve(self, query: str, budget_chars: int = 6000) -> str:
        """Targeted context for a question: matching symbols with a few surrounding lines."""
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        hits: list[tuple[int, Symbol]] = []
        for s in self.symbols():
            score = sum(1 for w in words if w in s.name.lower() or w in s.file.lower())
            if score:
                hits.append((score, s))
        hits.sort(key=lambda t: (-t[0], t[1].file, t[1].line))
        out, used = [], 0
        for _, s in hits:
            try:
                lines = open(os.path.join(self.root, s.file), encoding="utf-8", errors="replace").read().splitlines()
            except OSError:
                continue
            snippet = "\n".join(lines[max(0, s.line - 1) : s.line + 14])
            block = f"# {s.file}:{s.line} ({s.kind} {s.name})\n{snippet}\n"
            if used + len(block) > budget_chars:
                break
            out.append(block)
            used += len(block)
        return "\n".join(out)

    def summary(self) -> str:
        return f"{len(self.files)} files, {len(self.symbols())} symbols, {len(self.todos())} TODOs"
