"""Quick-command routing for the desktop chat bubble.

``route(text)`` turns ``/code``, ``/fix``, ``/git`` … (and plain text) into one of three outcomes so the UI never
has to know the command table: reply locally, open a window, or send a (possibly rewritten) prompt to the AI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .chat_commands import handle_chat_command
from .commands import COMMANDS

HELP = (
    "/chat  /explain <text>  /fix <error>  /learn <topic>  /search <query>\n"
    "/code  /git  /github  /test  /run  → open the coding workspace (tools, diff, terminal)\n"
    "/remind  /settings  /privacy  → open that window\n"
    "/remember <text>  /memory  /forget <id>  /forget-all"
)

_WORKSPACE = {"code", "git", "github", "test", "run"}
_WINDOWS = {"remind": "open_reminder", "settings": "open_settings", "privacy": "open_privacy"}
_REWRITE = {
    "explain": "Explain this clearly for a developer. Use the user's language; keep code in English:\n{args}",
    "fix": "Find the likely cause of this problem, explain it and propose a minimal fix:\n{args}",
    "learn": "Teach me this step by step as a patient tutor (explain, then a small example, then an exercise):\n{args}",
    "chat": "{args}",
}


@dataclass
class QuickResult:
    kind: str  # "reply" | "action" | "ai" | "task" (slow, run off the UI thread)
    text: str = ""  # reply text, or the prompt to send to the AI
    action: str = ""  # method name on the main window
    func: Callable[[], str] | None = None  # for "task": blocking work to run in a background worker


def _search(args: str) -> str:
    from . import secret_store
    from .agent.tools import ToolError
    from .web.search import BraveSearchProvider

    if not args:
        return "Usage: /search <query>"
    try:
        results = BraveSearchProvider(lambda: secret_store.get_secret("brave_api_key")).search(args, 5)
    except ToolError as exc:
        return f"Search unavailable: {exc}"
    except Exception as exc:  # noqa: BLE001 - offline etc. must not crash the chat
        return f"Search failed: {exc}"
    return "\n\n".join(f"{r.title}\n{r.url}\n{r.snippet}" for r in results) or "No results."


def route(text: str) -> QuickResult | None:
    """Return how to handle ``text``, or None for ordinary natural-language chat."""
    text = text.strip()
    if not text.startswith("/"):
        return None
    mem = handle_chat_command(text)
    if mem is not None:
        return QuickResult("reply", mem)
    name, _, args = text[1:].partition(" ")
    name, args = name.lower(), args.strip()
    if name == "help":
        return QuickResult("reply", HELP)
    if name in _WINDOWS:
        return QuickResult("action", action=_WINDOWS[name])
    if name in _WORKSPACE:
        return QuickResult("action", action="open_workspace")
    if name == "search":
        return QuickResult("task", func=lambda: _search(args))
    if name in _REWRITE:
        if not args:
            return QuickResult("reply", f"Usage: /{name} <text>")
        return QuickResult("ai", _REWRITE[name].format(args=args))
    if name in COMMANDS:  # known but unhandled: be explicit instead of silently doing nothing
        return QuickResult("reply", HELP)
    return None  # unknown slash text goes to the AI as-is
