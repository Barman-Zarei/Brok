"""Memory commands for the desktop chat bubble: /remember, /memory, /forget, /forget-all."""

from __future__ import annotations

from .config import BrokConfig
from .memory import MemoryStore, SensitiveContentError

HELP = "/remember <text> · /memory · /forget <id> · /forget-all"


def handle_chat_command(text: str, store: MemoryStore | None = None, enabled: bool | None = None) -> str | None:
    """Return the reply for a memory command, or None when ``text`` is not one (send it to the AI)."""
    head, _, rest = text.strip().partition(" ")
    cmd, rest = head.lower(), rest.strip()
    if cmd not in ("/remember", "/memory", "/forget", "/forget-all"):
        return None
    if enabled is None:
        enabled = BrokConfig.load().memory.enabled
    if not enabled:
        return "Memory is turned off (memory.enabled = false)."
    store = store or MemoryStore()
    if cmd == "/remember":
        if not rest:
            return "Usage: /remember <text>"
        try:
            item = store.add("longterm", rest)
        except SensitiveContentError as exc:
            return f"Not saved: {exc}"
        return f"Saved ({item.id}). Remove it with /forget {item.id}"
    if cmd == "/memory":
        items = store.list()
        return "\n".join(f"{i.id}  [{i.kind}] {i.text}" for i in items) or "Memory is empty. " + HELP
    if cmd == "/forget":
        return "Forgotten." if rest and store.delete(rest) else "No memory with that id (see /memory)."
    return f"Cleared {store.clear()} item(s)."


def memory_block(store: MemoryStore | None = None, enabled: bool | None = None) -> str:
    """Text injected into the chat system prompt ('' when memory is off or empty)."""
    try:
        if enabled is None:
            enabled = BrokConfig.load().memory.enabled
        if not enabled:
            return ""
        return (store or MemoryStore()).context_for()
    except Exception:  # noqa: BLE001 - a broken memory file must never break chat
        return ""
