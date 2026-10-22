"""Command safety: classify before executing; never unrestricted shell."""

from __future__ import annotations

import os
import platform
import re
import shlex
import subprocess
from dataclasses import dataclass, field

SAFE, CONFIRM, BLOCKED = "safe", "confirm", "blocked"

# Read-only commands that may run without asking.
_SAFE_PROGRAMS = {"ls", "dir", "pwd", "cat", "head", "tail", "wc", "echo", "whoami", "which", "where", "type", "date"}
_SAFE_GIT = {"status", "diff", "log", "branch", "show", "rev-parse", "remote"}

_BLOCK_PATTERNS = [
    (
        r"\brm\b(?=[^;&|\n]*\s(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)(?:\s|$))"
        r"[^;&|\n]*\s(?:/|~|\$HOME|\$\{HOME\}|\*|\.\.?)/?\*?(?=\s|$|[;&|])",
        "recursive destructive deletion",
    ),
    (r"\bmkfs(\.\w+)?\b", "disk formatting"),
    (r"\bdd\b.*\bof=/dev/", "raw disk write"),
    (r">\s*/dev/(sd|nvme|hd|disk)", "raw disk write"),
    (r":\(\)\s*\{.*\};\s*:", "fork bomb"),
    (r"\bchmod\s+-R\s+[0-7]*7[0-7]*\s+/(\s|$)", "recursive permission change on /"),
    (r"(?i)\bformat\s+[a-z]:", "disk formatting"),
    (r"(?i)\b(del|erase)\b.*\s/[sq]\b", "recursive deletion"),
    (r"(?i)\b(rd|rmdir)\b.*\s/s\b", "recursive deletion"),
    (
        r"(?i)(\.ssh/id_|\.aws/credentials|/etc/shadow|\.gnupg|\.netrc|login\.keychain|credentials\.json)",
        "credential access",
    ),
    (r"(?i)(^|[\s/\\=])\.env(\.[\w.-]+)?(?=\s|$|[\"';&|])", "secrets file (.env)"),
    (r"(?i)\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "pipe remote script to shell"),
    (r"(?i)\bgit\s+push\b.*--mirror", "remote mirror push"),
]
_CONFIRM_PATTERNS = [
    (r"\bsudo\b|\bsu\b\s", "elevated privileges"),
    (r"(?i)\bgit\s+push\b", "remote repository change"),
    (r"(?i)\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--|rebase)", "history/working tree destructive"),
    (r"(?i)\b(pip|npm|yarn|apt|apt-get|brew|choco|winget)\s+(un)?install\b", "package installation"),
    (r"(?i)\b(systemctl|service|reg|sc|launchctl|shutdown|reboot|kill|pkill|taskkill)\b", "system modification"),
    (r"\brm\b|\bmv\b|\bchmod\b|\bchown\b", "file modification"),
    (r"(?i)\b(curl|wget|scp|rsync|ssh|nc|ncat)\b", "network access"),
]
# Options that make an otherwise read-only git subcommand write files or read outside the repository.
_GIT_UNSAFE_OPTS = ("--output", "--ext-diff", "--textconv", "--no-index", "--exec-path", "--upload-pack")
_GIT_BRANCH_OK = {"-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "--list", "-l", "--show-current"}
_META = re.compile(r"[;&|`><]|\$\(|\n")


@dataclass
class Verdict:
    level: str
    reasons: list[str] = field(default_factory=list)
    shell: str = ""
    os_name: str = ""

    @property
    def allowed(self) -> bool:
        return self.level != BLOCKED


def _git_is_read_only(argv: list[str]) -> bool:
    sub, rest = argv[1], argv[2:]
    if any(a.startswith(_GIT_UNSAFE_OPTS) for a in rest):
        return False
    if sub == "branch":  # `git branch -D x` / `-m` / `new-branch` modify refs
        return all(a in _GIT_BRANCH_OK for a in rest)
    if sub == "remote":  # `git remote add/remove/set-url`
        return all(a in ("-v", "--verbose") for a in rest)
    return True


def _leaves_project(arg: str) -> bool:
    """Absolute, home-relative or parent-escaping path: a "read-only" command could then read anything on disk."""
    a = arg.strip("\"'")
    if a.startswith("-"):
        return False
    return a.startswith(("/", "~", "\\")) or (len(a) > 1 and a[1] == ":") or ".." in re.split(r"[\\/]", a)


def detect_shell(os_name: str | None = None) -> str:
    os_name = os_name or platform.system()
    return "cmd/powershell" if os_name == "Windows" else (os.path.basename(os.environ.get("SHELL", "")) or "sh")


def classify_command(command: str, os_name: str | None = None) -> Verdict:
    os_name = os_name or platform.system()
    v = Verdict(SAFE, [], detect_shell(os_name), os_name)
    cmd = command.strip()
    if not cmd:
        return Verdict(BLOCKED, ["empty command"], v.shell, os_name)
    for pat, why in _BLOCK_PATTERNS:
        if re.search(pat, cmd):
            return Verdict(BLOCKED, [why], v.shell, os_name)
    reasons = [why for pat, why in _CONFIRM_PATTERNS if re.search(pat, cmd)]
    if _META.search(cmd):
        reasons.append("shell operators (chaining/redirection)")
    if not reasons:
        try:
            argv = shlex.split(cmd, posix=os_name != "Windows")
        except ValueError:
            return Verdict(CONFIRM, ["unparseable command"], v.shell, os_name)
        prog = os.path.basename(argv[0]).lower() if argv else ""
        if prog == "git" and len(argv) > 1 and argv[1] in _SAFE_GIT:
            if _git_is_read_only(argv):
                return v
            reasons.append("git option that writes or modifies")
        elif prog in _SAFE_PROGRAMS:
            if not any(_leaves_project(a) for a in argv[1:]):
                return v
            reasons.append("path outside the project")
        else:
            reasons.append("runs an unlisted program")
    return Verdict(CONFIRM, reasons, v.shell, os_name)


_SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)


def scrubbed_env() -> dict[str, str]:
    """Environment without secrets, so executed commands cannot read API keys."""
    return {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}


@dataclass
class CommandResult:
    returncode: int
    output: str
    timed_out: bool = False


def run_command(
    command: str, cwd: str, timeout: int = 120, max_output: int = 20000, os_name: str | None = None
) -> CommandResult:
    """Run without a shell (argv list). Caller must already have classified/approved."""
    import shlex as _sh

    posix = (os_name or platform.system()) != "Windows"
    argv = _sh.split(command, posix=posix)
    if not posix:  # shlex(posix=False) keeps the surrounding quotes in each token; the program must not see them
        argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'" else a for a in argv]
    try:
        p = subprocess.run(
            argv,
            cwd=cwd,
            env=scrubbed_env(),
            capture_output=True,
            timeout=timeout,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        parts = [x.decode("utf-8", "replace") if isinstance(x, bytes) else (x or "") for x in (exc.stdout, exc.stderr)]
        return CommandResult(-1, "".join(parts)[-max_output:] + f"\n[timed out after {timeout}s]", True)
    except (OSError, ValueError) as exc:
        return CommandResult(-1, f"cannot run: {exc}")
    out = (p.stdout or "") + (p.stderr or "")
    if len(out) > max_output:
        out = out[: max_output // 2] + "\n…[truncated]…\n" + out[-max_output // 2 :]
    return CommandResult(p.returncode, out)
