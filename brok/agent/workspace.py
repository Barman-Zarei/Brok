"""Workspace jail: every path the agent touches must stay inside the project root."""

from __future__ import annotations

import os
from pathlib import Path

from .tools import ToolError

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".idea",
    ".dart_tool",
    ".gradle",
    "target",
}
_BLOCKED_NAMES = {".env", "id_rsa", "id_ed25519", ".netrc", "credentials.json"}


class Workspace:
    def __init__(self, root: str) -> None:
        self.root = Path(os.path.realpath(root))
        if not self.root.is_dir():
            raise ToolError(f"project root is not a directory: {root}")

    def resolve(self, rel: str, must_exist: bool = False) -> Path:
        if not isinstance(rel, str) or not rel.strip() or "\x00" in rel:
            raise ToolError("invalid path")
        p = Path(os.path.realpath(self.root / rel))
        if p != self.root and self.root not in p.parents:
            raise ToolError(f"path escapes the project: {rel}")
        if must_exist and not p.exists():
            raise ToolError(f"no such file or directory: {rel}")
        return p

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root)) if p != self.root else "."

    @staticmethod
    def is_sensitive(p: Path) -> bool:
        return p.name in _BLOCKED_NAMES or p.name.startswith(".env.") or p.suffix in (".pem", ".key")
