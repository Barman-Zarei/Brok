"""The controlled tool set of the coding agent, all jailed to one project root."""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional

from .diff import unified_diff
from .index import ProjectIndex
from .project import detect_project
from .sandbox import BLOCKED, CONFIRM, classify_command, run_command, scrubbed_env
from .tools import Confirm, PermissionPolicy, Risk, ToolError, ToolRegistry, ToolSpec
from .workspace import SKIP_DIRS, Workspace

MAX_READ = 200_000
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,100}$")  # git ref/branch names: no leading '-' (option injection)


def _obj(props: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


_S = {"type": "string"}


def build_registry(root: str, policy: Optional[PermissionPolicy] = None, command_timeout: int = 120,
                   on_file_read: Optional[Callable[[str, int], None]] = None) -> ToolRegistry:
    ws = Workspace(root)
    reg = ToolRegistry(policy)
    state: Dict[str, Any] = {"index": None}

    def index() -> ProjectIndex:
        if state["index"] is None:
            state["index"] = ProjectIndex(str(ws.root)).build()
        return state["index"]

    # ---------------- read-only ----------------
    def read_file(path: str, start_line: int = 1, max_lines: int = 400) -> str:
        p = ws.resolve(path, must_exist=True)
        if not p.is_file():
            raise ToolError("not a file")
        if ws.is_sensitive(p):
            raise ToolError("refusing to read a secrets file (.env / keys); ask the user for the specific value instead")
        if p.stat().st_size > MAX_READ * 5:
            raise ToolError("file too large; use search_text or read a line range")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        chunk = lines[max(0, start_line - 1): max(0, start_line - 1) + max_lines]
        text = "\n".join(f"{start_line + i}: {l}" for i, l in enumerate(chunk))
        if on_file_read:
            on_file_read(ws.rel(p), len(text))
        return text + (f"\n[… {len(lines)} lines total]" if len(lines) > start_line - 1 + max_lines else "")

    def list_directory(path: str = ".") -> str:
        p = ws.resolve(path, must_exist=True)
        if not p.is_dir():
            raise ToolError("not a directory")
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        return "\n".join(("[dir] " if i.is_dir() else "") + i.name for i in items if i.name not in SKIP_DIRS) or "(empty)"

    def search_text(pattern: str, path: str = ".", max_results: int = 50) -> str:
        base = ws.resolve(path, must_exist=True)
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"bad regex: {exc}")
        out: List[str] = []
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            for fn in fns:
                fp = os.path.join(dp, fn)
                if ws.is_sensitive(ws.resolve(os.path.relpath(fp, ws.root))):
                    continue
                try:
                    if os.path.getsize(fp) > MAX_READ:
                        continue
                    for i, line in enumerate(open(fp, encoding="utf-8", errors="ignore"), 1):
                        if rx.search(line):
                            out.append(f"{os.path.relpath(fp, ws.root)}:{i}: {line.strip()[:200]}")
                            if len(out) >= max_results:
                                return "\n".join(out)
                except OSError:
                    continue
        return "\n".join(out) or "no matches"

    def search_code(query: str) -> str:
        syms = index().find_symbol(query)
        ctx = index().retrieve(query, 3000)
        head = "\n".join(f"{s.file}:{s.line} {s.kind} {s.name}" for s in syms) or "no symbol matches"
        return head + ("\n\n" + ctx if ctx else "")

    def inspect_project() -> str:
        i = detect_project(str(ws.root))
        return (f"languages={i.languages} frameworks={i.frameworks} package_managers={i.package_managers} "
                f"entry_points={i.entry_points} tests={i.test_command} lint={i.lint_command} build={i.build_system} "
                f"git={i.git_repo}\nindex: {index().summary()}")

    # ---------------- edits ----------------
    def _preview_write(a: Dict[str, Any]) -> Optional[str]:
        try:
            p = ws.resolve(a["path"])
            before = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
            return unified_diff(before, a["content"], a["path"])
        except (ToolError, KeyError, OSError):
            return None

    def write_file(path: str, content: str) -> str:
        p = ws.resolve(path)
        if ws.is_sensitive(p):
            raise ToolError("refusing to write secrets files")
        if not p.is_file():
            raise ToolError("file does not exist; use create_file")
        p.write_text(content, encoding="utf-8")
        state["index"] = None
        return f"wrote {path} ({len(content)} chars)"

    def create_file(path: str, content: str) -> str:
        p = ws.resolve(path)
        if p.exists():
            raise ToolError("already exists; use write_file")
        if ws.is_sensitive(p):
            raise ToolError("refusing to write secrets files")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        state["index"] = None
        return f"created {path}"

    def move_file(src: str, dst: str) -> str:
        a, b = ws.resolve(src, must_exist=True), ws.resolve(dst)
        if b.exists():
            raise ToolError("destination exists")
        b.parent.mkdir(parents=True, exist_ok=True)
        a.rename(b)
        state["index"] = None
        return f"moved {src} -> {dst}"

    def delete_file(path: str) -> str:
        p = ws.resolve(path, must_exist=True)
        if p == ws.root or p == ws.root / ".git":
            raise ToolError("refusing to delete the project root or .git")
        if p.is_dir():
            if any(p.iterdir()):
                raise ToolError("directory not empty; delete files individually")
            p.rmdir()
        else:
            p.unlink()
        state["index"] = None
        return f"deleted {path}"

    # ---------------- git ----------------
    def git(*args: str) -> str:
        try:
            p = subprocess.run(["git", *args], cwd=str(ws.root), env=scrubbed_env(), capture_output=True, text=True,
                               errors="replace", timeout=command_timeout, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolError(f"git failed: {exc}")
        out = (p.stdout + p.stderr).strip()
        if p.returncode:
            raise ToolError(out[-2000:] or f"git exited {p.returncode}")
        return out[-20000:] or "(no output)"

    def ref(name: str) -> str:
        if not _REF.match(name or "") or ".." in name:
            raise ToolError("invalid branch/ref name")
        return name

    git_status = lambda: git("status", "--short", "--branch")  # noqa: E731
    git_diff = lambda staged=False: git("diff", *(["--staged"] if staged else []))  # noqa: E731
    git_log = lambda limit=10: git("log", "--oneline", f"-{max(1, min(int(limit), 100))}")  # noqa: E731
    git_branch = lambda: git("branch", "--all")  # noqa: E731
    git_checkout = lambda branch, create=False: git("checkout", *(["-b"] if create else []), ref(branch))  # noqa: E731
    git_stash = lambda action="push": git("stash", action if action in ("push", "pop", "list") else "push")  # noqa: E731

    def git_commit(message: str) -> str:
        if not message.strip():
            raise ToolError("empty commit message")
        # Never stage secrets by accident (.env, keys) when committing "everything".
        excludes = [":(exclude,glob)**/" + n for n in (".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519", ".netrc",
                                                  "credentials.json")]
        git("add", "-A", "--", ".", *excludes)
        return git("commit", "-m", message)

    def git_push(remote: str = "origin", branch: str = "") -> str:
        return git("push", ref(remote), *([ref(branch)] if branch else []))

    # ---------------- commands ----------------
    def _cmd_dynamic(a: Dict[str, Any]):
        v = classify_command(a.get("command", ""))
        if v.level == BLOCKED:
            return Risk.CRITICAL, Confirm.ALWAYS, "BLOCKED: " + "; ".join(v.reasons)
        if v.level == CONFIRM:
            crit = any("remote" in r or "elevated" in r or "system" in r for r in v.reasons)
            return (Risk.CRITICAL if crit else Risk.HIGH), Confirm.ALWAYS if crit else Confirm.REQUIRED, \
                f"Run `{a.get('command')}` ({'; '.join(v.reasons)})"
        return Risk.LOW, Confirm.NEVER, "read-only command"

    def _cmd_precheck(a: Dict[str, Any]) -> Optional[str]:
        v = classify_command(a.get("command", ""))
        return ("command blocked as dangerous: " + "; ".join(v.reasons)) if v.level == BLOCKED else None

    def run_cmd(command: str) -> str:
        v = classify_command(command)
        if v.level == BLOCKED:  # blocked commands never run, even if somehow approved
            raise ToolError("command blocked as dangerous: " + "; ".join(v.reasons))
        r = run_command(command, str(ws.root), command_timeout)
        return f"exit={r.returncode}\n{r.output}"

    def _project_cmd(kind: str) -> str:
        info = detect_project(str(ws.root))
        cmd = {"test": info.test_command, "lint": info.lint_command, "format": info.format_command}[kind]
        if not cmd:
            raise ToolError(f"no {kind} command detected for this project")
        r = run_command(cmd, str(ws.root), command_timeout)
        return f"$ {cmd}\nexit={r.returncode}\n{r.output}"

    T = ToolSpec
    L, M, H, C = Risk.LOW, Risk.MEDIUM, Risk.HIGH, Risk.CRITICAL
    N, CFG, REQ, ALW = Confirm.NEVER, Confirm.CONFIGURABLE, Confirm.REQUIRED, Confirm.ALWAYS
    specs = [
        T("read_file", "Read a text file (with line numbers).", _obj({"path": _S, "start_line": {"type": "integer"},
          "max_lines": {"type": "integer"}}, ["path"]), L, N, read_file),
        T("list_directory", "List a directory.", _obj({"path": _S}, []), L, N, list_directory),
        T("search_text", "Regex search across project files.", _obj({"pattern": _S, "path": _S}, ["pattern"]), L, N, search_text),
        T("search_code", "Find symbols and relevant code by name.", _obj({"query": _S}), L, N, search_code),
        T("inspect_project", "Detect language/framework/tests of the project.", _obj({}), L, N, inspect_project),
        T("write_file", "Overwrite an existing file with new full content (shows a diff first).",
          _obj({"path": _S, "content": _S}), M, CFG, write_file, preview=_preview_write),
        T("create_file", "Create a new file.", _obj({"path": _S, "content": _S}), M, CFG, create_file, preview=_preview_write),
        T("move_file", "Move/rename a file.", _obj({"src": _S, "dst": _S}), M, CFG, move_file),
        T("delete_file", "Delete a file or empty directory.", _obj({"path": _S}), H, REQ, delete_file),
        T("git_status", "git status.", _obj({}), L, N, git_status),
        T("git_diff", "git diff (optionally staged).", _obj({"staged": {"type": "boolean"}}, []), L, N, git_diff),
        T("git_log", "Recent commits.", _obj({"limit": {"type": "integer"}}, []), L, N, git_log),
        T("git_branch", "List branches.", _obj({}), L, N, git_branch),
        T("git_checkout", "Switch/create a branch.", _obj({"branch": _S, "create": {"type": "boolean"}}, ["branch"]), M, CFG, git_checkout),
        T("git_stash", "Stash push/pop/list.", _obj({"action": _S}, []), M, CFG, git_stash),
        T("git_commit", "Stage everything and commit.", _obj({"message": _S}), H, REQ, git_commit),
        T("git_push", "Push to a remote (always asks).", _obj({"remote": _S, "branch": _S}, []), C, ALW, git_push),
        T("run_command", "Run a command (no shell). Risky commands need approval; dangerous ones are blocked.",
          _obj({"command": _S}), H, REQ, run_cmd, dynamic=_cmd_dynamic, precheck=_cmd_precheck),
        T("run_tests", "Run the project's test command.", _obj({}), M, CFG, lambda: _project_cmd("test")),
        T("run_linter", "Run the project's linter.", _obj({}), M, CFG, lambda: _project_cmd("lint")),
        T("run_formatter", "Run the project's formatter (modifies files).", _obj({}), M, CFG, lambda: _project_cmd("format")),
    ]
    for s in specs:
        reg.register(s)
    return reg
