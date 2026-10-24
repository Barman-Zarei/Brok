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
        self._check_inside(p, rel)
        if must_exist and not p.exists():
            raise ToolError(f"no such file or directory: {rel}")
        return p

    def resolve_link(self, rel: str, must_exist: bool = False) -> Path:
        """Like :meth:`resolve`, but a symlink in the last position is *not* followed (delete/move act on the link)."""
        if not isinstance(rel, str) or not rel.strip() or "\x00" in rel:
            raise ToolError("invalid path")
        joined = os.path.normpath(os.path.join(str(self.root), rel))
        p = Path(os.path.realpath(os.path.dirname(joined))) / os.path.basename(joined)
        self._check_inside(p, rel)
        if must_exist and not os.path.lexists(p):
            raise ToolError(f"no such file or directory: {rel}")
        return p

    def _check_inside(self, p: Path, rel: str) -> None:
        if p != self.root and self.root not in p.parents:
            raise ToolError(f"path escapes the project: {rel}")
        # .git holds hooks and config that git executes (core.fsmonitor, hooks/*): never reachable through file tools.
        if p != self.root and ".git" in p.relative_to(self.root).parts:
            raise ToolError("the .git directory is off-limits to file tools; use the git tools")

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root)) if p != self.root else "."

    @staticmethod
    def is_sensitive(p: Path) -> bool:
        return p.name in _BLOCKED_NAMES or p.name.startswith(".env.") or p.suffix in (".pem", ".key")
